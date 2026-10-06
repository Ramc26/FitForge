const PLANS = {
    schedule: 'Classic Split',
    schedule_2: 'Enhanced Split',
    schedule_3: 'V-Tapper',
};
const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const DAY_SHORT = { Monday: 'Mon', Tuesday: 'Tue', Wednesday: 'Wed', Thursday: 'Thu', Friday: 'Fri', Saturday: 'Sat', Sunday: 'Sun' };
const EQUIPMENT = [
    ['dumbbells', 'Dumbbells'],
    ['bench', 'Bench'],
    ['lat_machine', 'Lat machine'],
    ['barbell', 'Barbell'],
    ['cable', 'Cable machine'],
    ['pec_deck', 'Pec deck'],
    ['seated_row', 'Seated row machine'],
    ['pullup_machine', 'Pull-up machine'],
];
const RULES = [
    'Lat machine: lat and back-width work only.',
    'Barbell: bench press only.',
    'Cable machine: triceps only.',
];
const SUGGESTIONS = [
    'What am I training today?',
    'What weight should I use?',
    'Can I replace this exercise?',
    'How am I progressing?',
    "Make today's workout shorter",
];
const RING = 2 * Math.PI * 52;

const state = {
    data: null,
    plan: localStorage.getItem('fitforge_plan') || 'schedule_3',
    theme: localStorage.getItem('fitforge_theme') === 'minimal' ? 'minimal' : 'flat',
    device: localStorage.getItem('fitforge_device') || 'ios',
    screen: 'home',
    viewDay: null,
    exerciseIndex: 0,
    setIndex: 0,
    showOptional: false,
    user: null,
    history: [],
    overview: null,
    backend: false,
    chat: [],
    conversationId: localStorage.getItem('fitforge_conversation') || '',
    contextExercise: null,
    sheet: false,
    rest: null,
    logging: false,
};

if (!PLANS[state.plan]) state.plan = 'schedule_3';

function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, (char) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[char]));
}

function todayName() {
    return DAYS[(new Date().getDay() + 6) % 7];
}

function todayStamp() {
    return new Date().toDateString();
}

function greeting() {
    const hour = new Date().getHours();
    if (hour < 12) return 'Good morning';
    if (hour < 17) return 'Good afternoon';
    return 'Good evening';
}

function nudgeFor(day) {
    if (!day) return 'Train what is on the card.';
    if (day.is_rest_day) return 'Rest is part of the program. Walk if you want, then leave the gym alone.';
    const focus = (day.focus || '').toLowerCase();
    if (focus.includes('pull') || focus.includes('back')) return "Let's make your back wider today.";
    if (focus.includes('push') || focus.includes('chest')) return 'Upper chest and shoulders today. Build the shelf.';
    if (focus.includes('leg')) return 'Leg day. Smooth reps, full range.';
    if (focus.includes('v-taper') || focus.includes('upper')) return 'Width day. Lats and side delts come first.';
    if (focus.includes('cardio')) return "Optional work. Walk, brace the core, or take the rest if you're cooked.";
    return "Train what's on the card. Leave a little in the tank.";
}

function estimateMinutes(day) {
    if (!day || day.is_rest_day) return 0;
    let total = 5 * 60;
    const blocks = [...(day.exercises || [])];
    if (day.finisher) blocks.push(day.finisher);
    blocks.forEach((exercise) => {
        const reps = String(exercise.reps || '');
        if (/minute/i.test(reps)) {
            const nums = (reps.match(/\d+/g) || []).map(Number);
            total += (nums.length ? Math.max(...nums) : 20) * 60;
            return;
        }
        if (exercise.duration_minutes) {
            total += Number(exercise.duration_minutes) * 60;
            return;
        }
        const sets = exercise.sets || 1;
        const rest = exercise.rest_seconds || 60;
        total += sets * (45 + rest) + 60;
    });
    return Math.max(1, Math.round(total / 60));
}

function midpointReps(reps) {
    const range = String(reps || '').match(/(\d+)\s*-\s*(\d+)/);
    if (range) return Math.round((Number(range[1]) + Number(range[2])) / 2);
    const single = String(reps || '').match(/(\d+)/);
    return single ? Number(single[1]) : 10;
}

function isBodyweight(exercise) {
    return /crunch|twist|plank|walk|push-up|pushup/i.test(exercise.name || '');
}

function schedule() {
    if (!state.data) return [];
    return state.data[state.plan] || state.data.schedule || [];
}

function dayByName(name) {
    return schedule().find((day) => day.day_of_week === name) || null;
}

function currentDay() {
    return dayByName(state.viewDay || todayName());
}

function emptyDay() {
    return { checkedSets: {}, finisherDone: false, hasCelebrated: false, inputs: {} };
}

function loadSession() {
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem('fitforge_state') || '{}'); } catch (err) { saved = {}; }
    if (saved.date !== todayStamp() || !saved.plans) {
        const plans = {};
        Object.keys(PLANS).forEach((key) => { plans[key] = { days: {} }; });
        saved = { date: todayStamp(), voiceEnabled: !!(saved && saved.voiceEnabled), plans };
    }
    Object.keys(PLANS).forEach((key) => {
        if (!saved.plans[key]) saved.plans[key] = { days: {} };
        if (!saved.plans[key].days) saved.plans[key].days = {};
    });
    state.session = saved;
}

function saveSession() {
    localStorage.setItem('fitforge_state', JSON.stringify(state.session));
}

function dayProgress(dayName = state.viewDay) {
    const plan = state.session.plans[state.plan];
    if (!plan.days[dayName]) plan.days[dayName] = emptyDay();
    if (!plan.days[dayName].inputs) plan.days[dayName].inputs = {};
    if (!plan.days[dayName].checkedSets) plan.days[dayName].checkedSets = {};
    return plan.days[dayName];
}

function playlist(day) {
    if (!day || day.is_rest_day) return [];
    const items = (day.exercises || []).map((exercise, index) => ({
        ...exercise, id: `ex${index}`, kind: 'main', sets: exercise.sets || 1,
    }));
    if (day.finisher) {
        items.push({ ...day.finisher, id: 'finisher', kind: 'finisher', sets: day.finisher.sets || 1 });
    }
    if (state.showOptional) {
        (day.optional_exercises || []).forEach((exercise, index) => {
            items.push({ ...exercise, id: `opt${index}`, kind: 'optional', sets: exercise.sets || 1 });
        });
    }
    return items;
}

function currentExercise() {
    const items = playlist(currentDay());
    if (!items.length) return null;
    if (state.exerciseIndex >= items.length) state.exerciseIndex = 0;
    return items[state.exerciseIndex];
}

function checked(id) {
    return dayProgress().checkedSets[id] || [];
}

function isSetDone(id, index) {
    return checked(id).includes(index);
}

function totals(day) {
    let total = 0;
    let done = 0;
    (day?.exercises || []).forEach((exercise, index) => {
        const sets = exercise.sets || 1;
        total += sets;
        done += checked(`ex${index}`).length;
    });
    if (day?.finisher) {
        const sets = day.finisher.sets || 1;
        total += sets;
        done += Math.min(checked('finisher').length, sets);
    }
    const pct = total ? Math.min(100, Math.round((done / total) * 100)) : 0;
    return { total, done, pct };
}

function lastSession(name) {
    const wanted = name.toLowerCase();
    const rows = state.history.filter((row) => (row.exercise_name || '').toLowerCase() === wanted);
    if (!rows.length) return null;
    const today = FitForgeAPI.todayISO();
    const dates = [...new Set(rows.map((row) => row.date))].filter((day) => day !== today).sort();
    const date = dates[dates.length - 1];
    const sets = {};
    rows.filter((row) => row.date === date).forEach((row) => {
        sets[row.set_number] = row;
    });
    return {
        date,
        sets: Object.keys(sets).sort((a, b) => a - b).map((key) => sets[key]),
    };
}

function bestLift() {
    let best = null;
    state.history.forEach((row) => {
        const weight = Number(row.weight_kg || 0);
        if (weight <= 0) return;
        const reps = Number(row.reps || 0);
        if (!best || weight > best.weight || (weight === best.weight && reps > best.reps)) {
            best = { name: row.exercise_name, weight, reps, date: row.date };
        }
    });
    return best;
}

function inputKey(exercise, setIndex) {
    return `${exercise.id}:${setIndex}`;
}

function readStoredInput(exercise, setIndex) {
    const stored = dayProgress().inputs[inputKey(exercise, setIndex)];
    if (stored) return stored;
    const previous = lastSession(exercise.name);
    const prior = previous?.sets?.[setIndex] || previous?.sets?.[0];
    return {
        weight: prior && prior.weight_kg != null ? prior.weight_kg : (isBodyweight(exercise) ? 0 : ''),
        reps: prior && prior.reps != null ? prior.reps : midpointReps(exercise.reps),
        rpe: '',
        note: '',
    };
}

function rememberInputs(exercise) {
    const weight = document.getElementById('weightInput');
    const reps = document.getElementById('repsInput');
    if (!weight || !exercise) return;
    dayProgress().inputs[inputKey(exercise, state.setIndex)] = {
        weight: weight.value,
        reps: reps ? reps.value : '',
        rpe: document.getElementById('rpeInput')?.value || '',
        note: document.getElementById('noteInput')?.value || '',
    };
    saveSession();
}

function toast(message) {
    const el = document.getElementById('toast');
    el.textContent = message;
    el.hidden = false;
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => { el.hidden = true; }, 3200);
}

function applyTheme(theme) {
    state.theme = theme === 'minimal' ? 'minimal' : 'flat';
    document.documentElement.setAttribute('data-theme', state.theme);
    localStorage.setItem('fitforge_theme', state.theme);
    document.getElementById('themeColor').setAttribute('content', state.theme === 'minimal' ? '#f5f2ee' : '#0d0b12');
}

function showScreen(name) {
    state.screen = name;
    state.sheet = false;
    state.logging = false;
    document.querySelectorAll('.screen').forEach((el) => {
        el.classList.toggle('is-on', el.id === `screen-${name}`);
    });
    document.querySelectorAll('.nav-btn').forEach((el) => {
        el.classList.toggle('is-active', el.dataset.screen === name);
    });
    document.getElementById('screen-hanu').classList.remove('sheet-mode');
    document.getElementById('backdrop').hidden = true;
    document.getElementById('closeHanu').hidden = true;
    document.getElementById('floatHanu').hidden = name !== 'workout';
    document.body.classList.remove('locked');
    if (name === 'home') renderHome();
    if (name === 'workout') renderWorkout();
    if (name === 'progress') {
        renderProgress();
        refreshRemote();
    }
    if (name === 'profile') renderProfile();
    if (name === 'hanu') {
        state.contextExercise = null;
        renderChat();
        loadCoachHistory();
    }
    document.querySelector('.app').scrollTo(0, 0);
}

function renderHome() {
    const day = currentDay();
    const calendar = todayName();
    const name = state.user?.name || 'Ram';
    const score = totals(day);
    const weight = state.overview?.current_weight_kg ?? state.user?.weight_kg;
    const consistency = state.overview?.consistency;
    const pr = bestLift();
    const label = state.viewDay === calendar ? 'Today' : state.viewDay;
    let todayBlock;
    if (!day) {
        todayBlock = `<article class="card"><p>No session for ${escapeHtml(state.viewDay)}.</p></article>`;
    } else if (day.is_rest_day) {
        todayBlock = `<article class="card hero rest">
            <p class="kicker">${label} · Recovery</p>
            <h3 class="focus">${escapeHtml(day.focus)}</h3>
            <p style="margin:0 0 6px">${escapeHtml(day.notes || 'Rest and recover.')}</p>
            <p class="quiet" style="margin:0">Tap another day above to catch up a session.</p>
        </article>`;
    } else {
        const lineup = playlist(day).map((exercise, index) => {
            const doneSets = checked(exercise.id).length;
            const done = doneSets >= (exercise.sets || 1);
            return `<li><button type="button" class="${done ? 'done' : ''}" data-jump="${index}">
                <span class="num">${done ? '✓' : index + 1}</span>
                <span><strong>${escapeHtml(exercise.name)}</strong><small>${exercise.kind === 'finisher' ? 'Finisher · ' : ''}${exercise.sets || 1} × ${escapeHtml(exercise.reps || `${exercise.duration_minutes || ''} min`)}</small></span>
                <span class="sets">${doneSets}/${exercise.sets || 1}</span>
            </button></li>`;
        }).join('');
        todayBlock = `<article class="card hero">
            ${state.viewDay !== calendar ? `<p class="catchup" style="margin:0 0 8px">Catch-up · today is ${calendar}</p>` : ''}
            <div class="hero-top">
                <div>
                    <p class="kicker">${label} · ${escapeHtml(PLANS[state.plan])}</p>
                    <h3 class="focus">${escapeHtml(day.focus)}</h3>
                </div>
                ${miniRing(score.pct)}
            </div>
            <div class="tags">
                <span class="tag">🏋️ ${day.exercises.length} lifts</span>
                <span class="tag">⏱ ~${estimateMinutes(day)} min</span>
                ${day.finisher ? '<span class="tag">🔥 Finisher</span>' : ''}
            </div>
            <button class="btn light" type="button" data-action="start">${score.done ? 'Continue workout' : 'Start workout'} →</button>
        </article>
        <article class="card">
            <div class="card-title"><h3>Lineup</h3><span class="quiet">${score.done}/${score.total} sets</span></div>
            <ul class="lineup">${lineup}</ul>
        </article>`;
    }
    const streak = consistency ? `${consistency.completed}/${consistency.expected}` : '—';
    document.getElementById('screen-home').innerHTML = `
        <p class="hello-sub">${greeting()},</p>
        <h2 class="hello">${escapeHtml(name)} <span class="wave">👋</span></h2>
        <div class="week">${weekChips()}</div>
        <p id="syncNote" class="sync-note" ${state.backend ? 'hidden' : ''}>Logging and Hanu sync when the server is back. Today's workout is on this phone.</p>
        ${todayBlock}
        <article class="card coach-card">
            <img class="hanu-avatar" src="images/fitnesscoach.png" alt="Hanu">
            <p class="quote">${escapeHtml(nudgeFor(day))}</p>
        </article>
        <button class="btn secondary" type="button" data-action="ask" style="margin-top:-2px">💬 Ask Hanu anything</button>
        <div class="stat-row" style="margin-top:14px">
            <article class="card stat"><span class="ico">⚖️</span><strong>${weight ? `${Number(weight).toFixed(1)}` : '—'}</strong><span>kg body weight</span></article>
            <article class="card stat"><span class="ico">📅</span><strong>${streak}</strong><span>sessions this week</span></article>
        </div>
        ${pr ? `<article class="card stat" style="flex-direction:row;align-items:center;justify-content:space-between">
            <div><span class="quiet">Best lift</span><strong style="font-size:1.1rem;display:block">${escapeHtml(pr.name)}</strong></div>
            <strong style="background:var(--grad);-webkit-background-clip:text;background-clip:text;color:transparent">${pr.weight}kg × ${pr.reps}</strong>
        </article>` : ''}
    `;
}

function weekChips() {
    const calendar = todayName();
    return DAYS.map((item) => {
        const classes = ['chip'];
        if (item === state.viewDay) classes.push('is-on');
        if (item === calendar) classes.push('is-today');
        if (dayByName(item)?.is_rest_day) classes.push('is-rest');
        return `<button class="${classes.join(' ')}" type="button" data-day="${item}" aria-label="${item}">${DAY_SHORT[item]}<span class="dot"></span></button>`;
    }).join('');
}

function miniRing(pct) {
    const r = 30;
    const c = 2 * Math.PI * r;
    return `<div class="mini-ring" aria-label="${pct}% done">
        <svg viewBox="0 0 74 74"><circle class="track" cx="37" cy="37" r="${r}"></circle>
        <circle class="fill" cx="37" cy="37" r="${r}" stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - pct / 100)}"></circle></svg>
        <span>${pct}%</span>
    </div>`;
}

function renderWorkout() {
    const day = currentDay();
    const calendar = todayName();
    const root = document.getElementById('screen-workout');
    const chips = `<div class="week" style="margin-top:0">${weekChips()}</div>`;
    if (!day || day.is_rest_day) {
        root.innerHTML = `
            ${chips}
            <article class="card hero rest">
                <p class="kicker">Recovery</p>
                <h2 class="focus">${escapeHtml(day?.focus || 'Rest')}</h2>
                <p style="margin:0 0 6px">${escapeHtml(day?.notes || 'Take the day off.')}</p>
                <p class="quiet" style="margin:0">Tap another day above to catch up a missed session.</p>
            </article>`;
        return;
    }
    const items = playlist(day);
    const exercise = currentExercise();
    const values = readStoredInput(exercise, state.setIndex);
    const previous = lastSession(exercise.name);
    const previousText = previous
        ? `${previous.sets.map((set) => set.weight_kg != null ? `${set.weight_kg}kg × ${set.reps}` : `${set.reps} reps`).join(' · ')}`
        : 'No previous weight recorded yet.';
    const pips = Array.from({ length: exercise.sets || 1 }, (_, index) => {
        const classes = ['set-pip'];
        if (isSetDone(exercise.id, index)) classes.push('is-done');
        if (index === state.setIndex) classes.push('is-current');
        return `<button class="${classes.join(' ')}" type="button" data-set="${index}">${index + 1}</button>`;
    }).join('');
    const optionalCount = (day.optional_exercises || []).length;
    const science = exercise.anatomy_pov ? `<p class="panel" id="panel-science">${escapeHtml(exercise.anatomy_pov)}</p>` : '';
    const form = exercise.form ? `<p class="panel" id="panel-form">${escapeHtml(exercise.form)}</p>` : '';
    const alt = exercise.machine_alternative ? `<p class="alt">Alt: ${escapeHtml(exercise.machine_alternative)}</p>` : '';
    const details = (science || form || alt)
        ? `<button class="disclosure" type="button" data-panel="details">Form & tips</button><div class="panel" id="panel-details" hidden>${science}${form}${alt}</div>`
        : '';
    const score = totals(day);
    const timed = /minute/i.test(exercise.reps || '') || exercise.duration_minutes;
    const target = exercise.reps || (exercise.duration_minutes ? `${exercise.duration_minutes} min` : '');
    if (state.logging && !timed) {
        root.innerHTML = `
            <article class="card log-card lift-card" style="margin-top:4px">
                <p class="kicker">Set ${state.setIndex + 1} of ${exercise.sets || 1} · target ${escapeHtml(target)}</p>
                <h2 class="lift-name">${escapeHtml(exercise.name)}</h2>
                <p class="quiet" style="margin:0">What did you lift?</p>
                <div class="steppers">
                    <div class="stepper-wrap">
                        <label for="weightInput">Weight · kg</label>
                        <div class="stepper">
                            <button type="button" data-step="weight" data-by="-2.5" aria-label="Less weight">−</button>
                            <input id="weightInput" inputmode="decimal" placeholder="0" value="${escapeHtml(values.weight)}">
                            <button type="button" data-step="weight" data-by="2.5" aria-label="More weight">+</button>
                        </div>
                    </div>
                    <div class="stepper-wrap">
                        <label for="repsInput">Reps</label>
                        <div class="stepper">
                            <button type="button" data-step="reps" data-by="-1" aria-label="Fewer reps">−</button>
                            <input id="repsInput" inputmode="numeric" value="${escapeHtml(values.reps)}">
                            <button type="button" data-step="reps" data-by="1" aria-label="More reps">+</button>
                        </div>
                    </div>
                </div>
                <p class="quiet" style="margin:4px 0 16px">Last time · ${escapeHtml(previousText)}</p>
                <button class="btn" type="button" data-action="save-log">Log set ✓</button>
                <button class="linkish" type="button" data-action="cancel-log">Back to exercise</button>
            </article>
        `;
        return;
    }
    const segments = items.map((item, index) => {
        const pct = Math.min(100, Math.round((checked(item.id).length / (item.sets || 1)) * 100));
        return `<i class="${index === state.exerciseIndex ? 'is-current' : ''}" style="--p:${pct}%"></i>`;
    }).join('');
    const label = exercise.kind === 'finisher' ? 'Finisher' : exercise.kind === 'optional' ? 'Optional' : `Exercise ${state.exerciseIndex + 1} of ${items.length}`;
    root.innerHTML = `
        ${chips}
        ${state.viewDay !== calendar ? `<p class="catchup">${state.viewDay} catch-up · today is ${calendar}</p>` : ''}
        <div class="wk-head">
            <h2>${escapeHtml(day.focus)}</h2>
            <span class="quiet">${score.done}/${score.total} sets</span>
        </div>
        <div class="segments">${segments}</div>
        <article class="card lift-card">
            <p class="kicker">${label}</p>
            <h2 class="lift-name">${escapeHtml(exercise.name)}</h2>
            <div class="tags">
                <span class="tag">${exercise.sets || 1} × ${escapeHtml(target)}</span>
                ${exercise.rest_seconds ? `<span class="tag">⏱ ${exercise.rest_seconds}s rest</span>` : ''}
            </div>
            <div class="last-time"><span>📈</span><div><b>Last time</b>${escapeHtml(previousText)}</div></div>
            <div class="set-pips">${pips}</div>
            ${details}
        </article>
        ${optionalCount ? `<button class="pill optional-toggle" type="button" data-action="optional">${state.showOptional ? 'Hide optional lifts' : `+ ${optionalCount} optional lift${optionalCount > 1 ? 's' : ''}`}</button>` : ''}
        <div class="lift-bar">
            <button class="nav-arrow" type="button" ${state.exerciseIndex > 0 ? `data-jump="${state.exerciseIndex - 1}"` : 'disabled'} aria-label="Previous exercise">←</button>
            <button class="btn" type="button" data-action="complete">${isSetDone(exercise.id, state.setIndex) ? 'Redo' : 'Finish'} set ${state.setIndex + 1}</button>
            <button class="nav-arrow" type="button" ${state.exerciseIndex < items.length - 1 ? `data-jump="${state.exerciseIndex + 1}"` : 'disabled'} aria-label="Next exercise">→</button>
        </div>
    `;
}

function renderProgress() {
    const overview = state.overview;
    const entries = (overview?.entries || []).filter((row) => row.weight_kg != null);
    const weights = entries.map((row) => Number(row.weight_kg));
    let chart = '<p class="quiet">Log a weigh-in to see the trend.</p>';
    if (weights.length >= 2) {
        const w = 320;
        const h = 120;
        const min = Math.min(...weights);
        const max = Math.max(...weights);
        const span = max - min || 1;
        const points = weights.map((value, index) => {
            const x = 8 + (index / (weights.length - 1)) * (w - 16);
            const y = h - 8 - ((value - min) / span) * (h - 16);
            return `${x},${y}`;
        }).join(' ');
        chart = `<svg class="chart" viewBox="0 0 ${w} ${h}"><polygon class="area" points="8,${h} ${points} ${w - 8},${h}"></polygon><polyline points="${points}"></polyline></svg>`;
    }
    const consistency = overview?.consistency;
    const prs = (overview?.prs || []).map((item) => `<div class="pr"><strong>${escapeHtml(item.exercise_name)}</strong><span>${item.weight_kg}kg × ${item.reps}</span></div>`).join('') || '<p class="quiet">No weighed sets yet.</p>';
    const strength = (overview?.strength || []).map((item) => {
        const delta = Number(item.latest_kg) - Number(item.previous_kg);
        return `<div class="pr"><strong>${escapeHtml(item.exercise_name)}</strong><span>${item.previous_kg} → ${item.latest_kg}kg (${delta >= 0 ? '+' : ''}${delta})</span></div>`;
    }).join('') || '<p class="quiet">Two sessions on the same lift will show a trend.</p>';
    const sessions = (overview?.recent_sessions || []).map((session) => {
        const names = (session.exercises || []).map((item) => item.exercise_name).join(', ');
        return `<div class="session"><strong>${escapeHtml(session.date)}</strong><span class="quiet">${escapeHtml(names)}</span></div>`;
    }).join('') || (state.overviewError
        ? `<p class="quiet">${escapeHtml(state.overviewError)}</p>`
        : `<p class="quiet">${overview ? 'No sessions logged yet.' : 'Loading your numbers…'}</p>`);
    const delta = overview?.weight_delta_kg;
    document.getElementById('screen-progress').innerHTML = `
        <h2 class="screen-title">Your progress</h2>
        <div class="stat-row">
            <article class="card stat"><span class="ico">⚖️</span><strong>${overview?.current_weight_kg ? Number(overview.current_weight_kg).toFixed(1) : '—'}</strong><span>kg${delta == null ? '' : ` · ${delta > 0 ? '+' : ''}${delta}`}</span></article>
            <article class="card stat"><span class="ico">🔥</span><strong>${consistency ? `${consistency.percent}%` : '—'}</strong><span>${consistency ? `${consistency.completed}/${consistency.expected} this week` : 'this week'}</span></article>
        </div>
        <article class="card"><div class="card-title"><h3>Body weight</h3></div>${chart}</article>
        <article class="card"><div class="card-title"><h3>Log a weigh-in</h3></div>
            <form id="weightForm">
                <div class="field-grid">
                    <div class="field"><label for="logWeight">Weight (kg)</label><input id="logWeight" inputmode="decimal" placeholder="72.5"></div>
                    <div class="field"><label for="logWaist">Waist (cm) · optional</label><input id="logWaist" inputmode="decimal"></div>
                </div>
                <button class="btn" type="submit">Save weigh-in</button>
            </form>
        </article>
        <article class="card"><div class="card-title"><h3>🏆 Personal records</h3></div>${prs}</article>
        <article class="card"><div class="card-title"><h3>Strength trend</h3></div>${strength}</article>
        <article class="card"><div class="card-title"><h3>Recent sessions</h3></div>${sessions}</article>
    `;
}

function selectedEquipment() {
    const saved = localStorage.getItem('fitforge_equipment');
    if (saved) {
        try { return JSON.parse(saved); } catch (err) { /* fall through */ }
    }
    return state.user?.equipment?.length ? state.user.equipment : EQUIPMENT.map(([id]) => id);
}

function renderProfile() {
    const user = state.user || { name: 'Ram', goal: 'Build a V-shaped body' };
    const equipment = new Set(selectedEquipment());
    const boxes = EQUIPMENT.map(([id, label]) => `
        <label class="check"><input type="checkbox" name="equipment" value="${id}" ${equipment.has(id) ? 'checked' : ''}> ${label}</label>
    `).join('');
    const plans = Object.entries(PLANS).map(([key, label]) => `<button class="pill ${state.plan === key ? 'is-on' : ''}" type="button" data-plan="${key}">${label}</button>`).join('');
    const voiceOn = !!state.session.voiceEnabled;
    document.getElementById('screen-profile').innerHTML = `
        <h2 class="screen-title">Profile</h2>
        <article class="card"><div class="card-title"><h3>Plan</h3></div><div class="pills">${plans}</div></article>
        <form id="profileForm" class="card">
            <div class="card-title"><h3>About you</h3></div>
            <div class="field"><label for="profileName">Name</label><input id="profileName" value="${escapeHtml(user.name || '')}"></div>
            <div class="field-grid">
                <div class="field"><label for="profileAge">Age</label><input id="profileAge" inputmode="numeric" value="${escapeHtml(user.age ?? '')}"></div>
                <div class="field"><label for="profileHeight">Height (cm)</label><input id="profileHeight" inputmode="decimal" value="${escapeHtml(user.height_cm ?? '')}"></div>
                <div class="field"><label for="profileWeight">Weight (kg)</label><input id="profileWeight" inputmode="decimal" value="${escapeHtml(user.weight_kg ?? '')}"></div>
            </div>
            <div class="field"><label for="profileGoal">Goal</label><input id="profileGoal" value="${escapeHtml(user.goal || '')}"></div>
            <div class="field"><label for="profilePrefs">Preferences</label><textarea id="profilePrefs" rows="2">${escapeHtml(user.preferences || '')}</textarea></div>
            <div class="card-title" style="margin-top:18px"><h3>Equipment</h3></div>
            <div class="check-grid">${boxes}</div>
            ${RULES.map((rule) => `<p class="quiet" style="margin:4px 0">${rule}</p>`).join('')}
            <button class="btn" type="submit" style="margin-top:16px">Save profile</button>
        </form>
        <article class="card">
            <div class="card-title"><h3>Look & feel</h3></div>
            <div class="pills">
                <button class="pill ${state.theme === 'flat' ? 'is-on' : ''}" type="button" data-theme-choice="flat">🌙 Dark</button>
                <button class="pill ${state.theme === 'minimal' ? 'is-on' : ''}" type="button" data-theme-choice="minimal">☀️ Light</button>
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:14px">
                <button class="btn secondary" type="button" data-action="voice">${voiceOn ? '🔊 Voice on' : '🔇 Voice off'}</button>
                <button class="btn secondary" type="button" data-action="share">↗ Share</button>
            </div>
        </article>
        <p class="footer-note">Designed by <a href="https://bikkina.vercel.app">itsmeramc</a>. Training advice is not medical advice.</p>
    `;
}

function renderChat() {
    const thread = document.getElementById('hanuThread');
    const chip = document.getElementById('hanuContext');
    if (state.contextExercise) {
        chip.hidden = false;
        chip.textContent = `You're on ${state.contextExercise}.`;
    } else {
        chip.hidden = true;
    }
    const avatar = '<img class="hanu-avatar sm" src="images/fitnesscoach.png" alt="">';
    if (!state.chat.length) {
        thread.innerHTML = `<div class="chat-empty">
            <img src="images/fitnesscoach.png" alt="Hanu">
            <h3>Hey ${escapeHtml(state.user?.name || 'Ram')}, I'm Hanu.</h3>
            <p>Weights, swaps, form, progress. Ask away.</p>
        </div>`;
    } else {
        thread.innerHTML = state.chat.map((item) => item.role === 'user'
            ? `<div class="msg user"><div class="bubble">${escapeHtml(item.message)}</div></div>`
            : `<div class="msg hanu">${avatar}<div class="bubble">${escapeHtml(item.message)}</div></div>`
        ).join('');
    }
    if (state.typing) thread.insertAdjacentHTML('beforeend', `<div class="msg hanu">${avatar}<div class="bubble typing" aria-label="Hanu is thinking"><i></i><i></i><i></i></div></div>`);
    thread.scrollTop = thread.scrollHeight;
    const suggestions = document.getElementById('hanuSuggestions');
    suggestions.innerHTML = state.chat.length
        ? ''
        : SUGGESTIONS.map((text) => `<button type="button" data-suggest="${escapeHtml(text)}">${escapeHtml(text)}</button>`).join('');
    localStorage.setItem('fitforge_chat', JSON.stringify({
        conversationId: state.conversationId,
        messages: state.chat.slice(-40),
    }));
}

function coachContext() {
    const context = {
        plan: state.plan,
        screen: state.sheet ? 'workout' : state.screen,
        current_day: state.viewDay,
        equipment: selectedEquipment(),
    };
    if (state.contextExercise) context.current_exercise = state.contextExercise;
    return context;
}

async function sendChat(text) {
    const message = text.trim();
    if (!message) return;
    state.chat.push({ role: 'user', message });
    state.typing = true;
    renderChat();
    document.getElementById('hanuInput').value = '';
    try {
        const data = await FitForgeAPI.chat({
            message,
            conversation_id: state.conversationId || null,
            context: coachContext(),
            recent_messages: state.chat.slice(0, -1).slice(-5).map((item) => ({
                role: item.role,
                message: item.message,
            })),
            recent_logs: state.history.slice(-40).map((row) => ({
                exercise_name: row.exercise_name,
                set_number: Number(row.set_number) || 1,
                weight_kg: row.weight_kg,
                reps: row.reps,
                date: row.date,
                day_of_week: row.day_of_week,
            })).filter((row) => row.exercise_name),
        });
        state.conversationId = data.conversation_id;
        localStorage.setItem('fitforge_conversation', data.conversation_id);
        state.chat.push({ role: 'assistant', message: data.message });
        state.backend = true;
    } catch (err) {
        state.chat.push({
            role: 'assistant',
            message: err.offline ? "Hanu is taking a break. Try again in a moment." : err.message,
        });
    } finally {
        state.typing = false;
        renderChat();
    }
}

function openHanu(fromWorkout) {
    const exercise = fromWorkout ? currentExercise() : null;
    state.contextExercise = exercise ? exercise.name : null;
    state.sheet = !!fromWorkout;
    const screen = document.getElementById('screen-hanu');
    if (fromWorkout) {
        screen.classList.add('sheet-mode');
        document.getElementById('backdrop').hidden = false;
        document.getElementById('closeHanu').hidden = false;
        document.body.classList.add('locked');
    } else {
        showScreen('hanu');
        state.contextExercise = null;
    }
    renderChat();
    loadCoachHistory();
}

function closeSheet() {
    state.sheet = false;
    document.getElementById('screen-hanu').classList.remove('sheet-mode');
    document.getElementById('backdrop').hidden = true;
    document.getElementById('closeHanu').hidden = true;
    document.body.classList.remove('locked');
}

async function saveLog(payload) {
    const queueKey = 'fitforge_log_queue';
    try {
        await FitForgeAPI.logSet(payload);
        state.backend = true;
        await flushQueue();
        refreshRemote();
    } catch (err) {
        const queue = JSON.parse(localStorage.getItem(queueKey) || '[]');
        queue.push(payload);
        localStorage.setItem(queueKey, JSON.stringify(queue));
        toast(err.offline
            ? "Saved on this phone. I'll sync the set when the server is back."
            : err.message);
    }
}

async function flushQueue() {
    const key = 'fitforge_log_queue';
    const queue = JSON.parse(localStorage.getItem(key) || '[]');
    if (!queue.length) return;
    const remain = [];
    let blocked = false;
    for (const item of queue) {
        if (blocked) {
            remain.push(item);
            continue;
        }
        try {
            await FitForgeAPI.logSet(item);
        } catch (err) {
            blocked = true;
            remain.push(item);
        }
    }
    localStorage.setItem(key, JSON.stringify(remain));
}

function startRest(seconds) {
    const total = Math.max(5, Number(seconds) || 60);
    state.rest = { end: Date.now() + total * 1000, total };
    document.getElementById('restOverlay').hidden = false;
    document.body.classList.add('locked');
    tickRest();
}

function tickRest() {
    if (!state.rest) return;
    const left = Math.max(0, Math.ceil((state.rest.end - Date.now()) / 1000));
    const minutes = String(Math.floor(left / 60)).padStart(2, '0');
    const seconds = String(left % 60).padStart(2, '0');
    document.getElementById('restReadout').textContent = left ? `${minutes}:${seconds}` : 'LIFT';
    const ring = document.getElementById('restRing');
    const fraction = state.rest.total ? left / state.rest.total : 0;
    ring.style.strokeDasharray = String(RING);
    ring.style.strokeDashoffset = String(RING * (1 - fraction));
    if (left <= 0) {
        finishRest();
        return;
    }
    state.rest.timer = setTimeout(tickRest, 200);
}

function finishRest() {
    clearTimeout(state.rest?.timer);
    state.rest = null;
    document.getElementById('restOverlay').hidden = true;
    if (!state.sheet) document.body.classList.remove('locked');
    if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
    if (state.session.voiceEnabled && 'speechSynthesis' in window) {
        const speech = new SpeechSynthesisUtterance('Rest over.');
        speech.rate = 1.1;
        window.speechSynthesis.speak(speech);
    }
}

function dismissRest() {
    clearTimeout(state.rest?.timer);
    state.rest = null;
    document.getElementById('restOverlay').hidden = true;
    if (!state.sheet) document.body.classList.remove('locked');
}

function addRest(seconds) {
    if (!state.rest) return;
    state.rest.end += seconds * 1000;
    state.rest.total += seconds;
}

async function completeSet() {
    const exercise = currentExercise();
    if (!exercise) return;
    rememberInputs(exercise);
    const timed = /minute/i.test(exercise.reps || '') || exercise.duration_minutes;
    const values = dayProgress().inputs[inputKey(exercise, state.setIndex)] || {
        weight: '', reps: '', rpe: '', note: '',
    };
    if (!timed && values.weight === '' && values.reps === '') {
        toast('Add the weight or the reps for this set.');
        state.logging = true;
        renderWorkout();
        return;
    }
    const progress = dayProgress();
    const done = new Set(progress.checkedSets[exercise.id] || []);
    const fresh = !done.has(state.setIndex);
    done.add(state.setIndex);
    progress.checkedSets[exercise.id] = [...done].sort((a, b) => a - b);
    if (exercise.id === 'finisher') {
        progress.finisherDone = progress.checkedSets.finisher.length >= (exercise.sets || 1);
    }
    saveSession();
    const weight = values.weight === '' ? null : Number(values.weight);
    const reps = values.reps === '' ? null : Number(values.reps);
    const payload = {
        exercise_name: exercise.name,
        set_number: state.setIndex + 1,
        weight_kg: Number.isFinite(weight) ? weight : null,
        reps: Number.isFinite(reps) ? reps : null,
        rpe: values.rpe === '' ? null : Number(values.rpe),
        notes: values.note || '',
        date: FitForgeAPI.todayISO(),
        day_of_week: state.viewDay,
    };
    state.history.push({ ...payload, created_at: new Date().toISOString() });
    saveLog(payload);
    state.logging = false;
    if (navigator.vibrate) navigator.vibrate(18);
    const day = currentDay();
    const score = totals(day);
    if (fresh && score.pct < 100 && (exercise.rest_seconds || 0) > 0) startRest(exercise.rest_seconds);
    if (state.setIndex < (exercise.sets || 1) - 1) {
        state.setIndex += 1;
    } else {
        const items = playlist(day);
        const next = items.findIndex((item, index) => index > state.exerciseIndex && checked(item.id).length < (item.sets || 1));
        if (next >= 0) {
            state.exerciseIndex = next;
            state.setIndex = 0;
        }
    }
    renderWorkout();
    const pip = document.querySelector('.set-pip.is-done');
    if (pip) pip.classList.add('pop');
    if (score.pct === 100 && !progress.hasCelebrated) {
        progress.hasCelebrated = true;
        saveSession();
        celebrate();
    }
}

function celebrate() {
    if (typeof confetti !== 'function') return;
    const colors = state.theme === 'minimal' ? ['#f08a2c', '#e8502f', '#c73383'] : ['#ffa53d', '#ff5a4e', '#e0399b', '#ffffff'];
    confetti({ particleCount: 90, spread: 70, origin: { y: 0.7 }, colors });
}

function stepValue(kind, delta) {
    const exercise = currentExercise();
    rememberInputs(exercise);
    const key = inputKey(exercise, state.setIndex);
    const current = dayProgress().inputs[key];
    const raw = Number(current[kind] || 0);
    const next = Math.max(0, Math.round((raw + delta) * 10) / 10);
    current[kind] = next;
    saveSession();
    renderWorkout();
}

function spotifyCatalog() {
    const audio = state.data?.audio || {};
    const items = (audio.playlists || []).map((item) => ({
        name: item.name,
        url: item.url,
        description: item.description || '',
        type: (item.type || 'playlist').toLowerCase(),
    }));
    (audio.podcasts || []).forEach((item) => {
        if (!items.some((entry) => entry.url === item.url || entry.name === item.name)) {
            items.push({ name: item.name, url: item.url, description: item.description || '', type: 'podcast' });
        }
    });
    return items;
}

function spotifyLink(url) {
    if (state.device === 'web') return url;
    try {
        const parsed = new URL(url);
        const parts = parsed.pathname.split('/').filter(Boolean);
        if (parts.length < 2) return url;
        const [type, id] = parts;
        if (state.device === 'ios') return `spotify:${type}:${id}`;
        if (state.device === 'android') return `intent://${type}/${id}#Intent;scheme=spotify;package=com.spotify.music;end`;
    } catch (err) { /* keep the web url */ }
    return url;
}

function openSpotify() {
    const pills = ['ios', 'android', 'web'].map((device) => `
        <button class="pill ${state.device === device ? 'is-on' : ''}" type="button" data-device="${device}">${device}</button>
    `).join('');
    document.getElementById('devicePills').innerHTML = pills;
    const groups = [
        ['playlist', 'Playlists'],
        ['podcast', 'Podcasts'],
    ];
    const catalog = spotifyCatalog();
    document.getElementById('spotifyList').innerHTML = groups.map(([type, label]) => {
        const rows = catalog.filter((item) => item.type === type);
        if (!rows.length) return '';
        return `<p class="kicker">${label}</p>` + rows.map((item) => `
            <a class="audio-item" href="${spotifyLink(item.url)}" target="_blank" rel="noopener">
                <strong>${escapeHtml(item.name)}</strong>
                <span class="quiet">${escapeHtml(item.description)}</span>
            </a>
        `).join('');
    }).join('') || '<p class="quiet">No Spotify links in data.json yet.</p>';
    document.getElementById('spotifyModal').hidden = false;
}

function numberOrNull(value) {
    if (value === '' || value == null) return null;
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
}

async function saveProfile(event) {
    event.preventDefault();
    const equipment = [...document.querySelectorAll('input[name="equipment"]:checked')].map((input) => input.value);
    localStorage.setItem('fitforge_equipment', JSON.stringify(equipment));
    const body = {
        name: document.getElementById('profileName').value.trim() || 'Ram',
        age: numberOrNull(document.getElementById('profileAge').value),
        height_cm: numberOrNull(document.getElementById('profileHeight').value),
        weight_kg: numberOrNull(document.getElementById('profileWeight').value),
        goal: document.getElementById('profileGoal').value.trim(),
        preferences: document.getElementById('profilePrefs').value.trim(),
        equipment,
    };
    state.user = { ...(state.user || {}), ...body, saved: true };
    localStorage.setItem('fitforge_profile', JSON.stringify(state.user));
    try {
        state.user = await FitForgeAPI.saveUser(body);
        state.backend = true;
        toast('Profile saved.');
    } catch (err) {
        toast(err.offline ? "Saved on this phone. I'll sync when the server is back." : err.message);
    }
    renderHome();
    renderProfile();
}

async function saveWeighIn(event) {
    event.preventDefault();
    const weight = numberOrNull(document.getElementById('logWeight').value);
    const waist = numberOrNull(document.getElementById('logWaist').value);
    if (weight == null && waist == null) {
        toast('Add a weight or a waist measurement.');
        return;
    }
    try {
        await FitForgeAPI.saveProgress({ weight_kg: weight, waist_cm: waist, notes: '' });
        toast('Weigh-in saved.');
        await refreshRemote();
        renderProgress();
        renderHome();
    } catch (err) {
        toast(err.message);
    }
}

function shareApp() {
    const payload = { title: 'FitForge', text: 'Train with Hanu.', url: location.href };
    if (navigator.share) navigator.share(payload).catch(() => {});
    else toast(location.href);
}

async function refreshRemote() {
    try {
        await FitForgeAPI.health();
        state.backend = true;
        if (state.screen === 'home') renderHome();
    } catch (err) {
        state.backend = false;
        if (state.screen === 'home') renderHome();
        return;
    }
    const [user, history, overview] = await Promise.allSettled([
        FitForgeAPI.getUser(),
        FitForgeAPI.history(),
        FitForgeAPI.progress(state.plan),
    ]);
    if (user.status === 'fulfilled') {
        state.user = user.value;
        if (user.value.equipment?.length) {
            localStorage.setItem('fitforge_equipment', JSON.stringify(user.value.equipment));
        }
    }
    if (history.status === 'fulfilled') state.history = history.value.logs || [];
    if (overview.status === 'fulfilled') {
        state.overview = overview.value;
        state.overviewError = '';
    } else if (!state.overview) {
        state.overviewError = overview.reason?.message || "FitForge couldn't load your progress. Try again.";
    }
    if (state.screen === 'home') renderHome();
    if (state.screen === 'progress') renderProgress();
    if (state.screen === 'profile') renderProfile();
    flushQueue();
}

async function loadCoachHistory() {
    if (!state.conversationId) return;
    try {
        const rows = await FitForgeAPI.coachHistory(state.conversationId);
        if (rows?.length) {
            state.chat = rows.map((row) => ({ role: row.role === 'assistant' ? 'assistant' : 'user', message: row.message }));
            renderChat();
        }
    } catch (err) { /* local chat remains */ }
}

function onClick(event) {
    const screenBtn = event.target.closest('.nav-btn');
    if (screenBtn) {
        const going = screenBtn.dataset.screen;
        if (going === 'hanu' && state.screen === 'workout') openHanu(true);
        else showScreen(going);
        return;
    }
    const dayBtn = event.target.closest('[data-day]');
    if (dayBtn) {
        state.viewDay = dayBtn.dataset.day;
        state.exerciseIndex = 0;
        state.setIndex = 0;
        state.logging = false;
        renderHome();
        if (state.screen === 'workout') renderWorkout();
        return;
    }
    const jump = event.target.closest('[data-jump]');
    if (jump) {
        rememberInputs(currentExercise());
        state.exerciseIndex = Number(jump.dataset.jump);
        state.setIndex = 0;
        state.logging = false;
        if (state.screen === 'workout') renderWorkout();
        else showScreen('workout');
        return;
    }
    const setBtn = event.target.closest('[data-set]');
    if (setBtn) {
        rememberInputs(currentExercise());
        state.setIndex = Number(setBtn.dataset.set);
        state.logging = false;
        renderWorkout();
        return;
    }
    const step = event.target.closest('[data-step]');
    if (step) {
        stepValue(step.dataset.step, Number(step.dataset.by));
        return;
    }
    const panel = event.target.closest('[data-panel]');
    if (panel) {
        const body = document.getElementById(`panel-${panel.dataset.panel}`);
        if (body) body.hidden = !body.hidden;
        return;
    }
    const plan = event.target.closest('[data-plan]');
    if (plan) {
        state.plan = plan.dataset.plan;
        localStorage.setItem('fitforge_plan', state.plan);
        state.exerciseIndex = 0;
        state.setIndex = 0;
        renderProfile();
        renderHome();
        refreshRemote().then(() => { if (state.screen === 'home') renderHome(); });
        return;
    }
    const theme = event.target.closest('[data-theme-choice]');
    if (theme) {
        applyTheme(theme.dataset.themeChoice);
        renderProfile();
        return;
    }
    const device = event.target.closest('[data-device]');
    if (device) {
        state.device = device.dataset.device;
        localStorage.setItem('fitforge_device', state.device);
        openSpotify();
        return;
    }
    const suggest = event.target.closest('[data-suggest]');
    if (suggest) {
        sendChat(suggest.dataset.suggest);
        return;
    }
    const rest = event.target.closest('[data-rest]');
    if (rest) {
        if (rest.dataset.rest === 'dismiss') dismissRest();
        else addRest(Number(rest.dataset.rest));
        return;
    }
    const action = event.target.closest('[data-action]');
    if (!action) return;
    if (action.dataset.action === 'start') {
        state.exerciseIndex = 0;
        state.setIndex = 0;
        state.logging = false;
        showScreen('workout');
    } else if (action.dataset.action === 'ask') {
        showScreen('hanu');
    } else if (action.dataset.action === 'complete') {
        const exercise = currentExercise();
        const timed = exercise && (/minute/i.test(exercise.reps || '') || exercise.duration_minutes);
        if (timed) completeSet();
        else {
            state.logging = true;
            renderWorkout();
        }
    } else if (action.dataset.action === 'cancel-log') {
        rememberInputs(currentExercise());
        state.logging = false;
        renderWorkout();
    } else if (action.dataset.action === 'save-log') {
        completeSet();
    } else if (action.dataset.action === 'optional') {
        state.showOptional = !state.showOptional;
        renderWorkout();
    } else if (action.dataset.action === 'voice') {
        state.session.voiceEnabled = !state.session.voiceEnabled;
        saveSession();
        renderProfile();
    } else if (action.dataset.action === 'share') {
        shareApp();
    }
}

document.addEventListener('click', onClick);
document.addEventListener('input', (event) => {
    if (['weightInput', 'repsInput', 'rpeInput', 'noteInput'].includes(event.target.id)) {
        rememberInputs(currentExercise());
    }
});
document.getElementById('hanuForm').addEventListener('submit', (event) => {
    event.preventDefault();
    sendChat(document.getElementById('hanuInput').value);
});
document.getElementById('closeHanu').addEventListener('click', closeSheet);
document.getElementById('newHanu').addEventListener('click', () => {
    state.chat = [];
    state.conversationId = '';
    localStorage.removeItem('fitforge_conversation');
    renderChat();
    document.getElementById('hanuInput').focus();
});
document.getElementById('backdrop').addEventListener('click', closeSheet);
document.getElementById('floatHanu').addEventListener('click', () => openHanu(true));
document.getElementById('spotifyBtn').addEventListener('click', openSpotify);
document.getElementById('closeSpotify').addEventListener('click', () => {
    document.getElementById('spotifyModal').hidden = true;
});
document.body.addEventListener('submit', (event) => {
    if (event.target.id === 'profileForm') saveProfile(event);
    if (event.target.id === 'weightForm') saveWeighIn(event);
});

async function init() {
    applyTheme(state.theme);
    loadSession();
    state.viewDay = todayName();
    try {
        state.chat = JSON.parse(localStorage.getItem('fitforge_chat') || '{}').messages || [];
    } catch (err) { state.chat = []; }
    try {
        state.user = JSON.parse(localStorage.getItem('fitforge_profile') || 'null');
    } catch (err) { state.user = null; }
    if (!localStorage.getItem('fitforge_user_id')) localStorage.setItem('fitforge_user_id', 'ram');
    if ('serviceWorker' in navigator) {
        window.addEventListener('load', () => navigator.serviceWorker.register('sw.js').catch(() => {}));
    }
    try {
        const response = await fetch('data.json', { cache: 'no-cache' });
        state.data = await response.json();
    } catch (err) {
        document.getElementById('screen-home').innerHTML = '<article class="card"><h2>FitForge needs its workout file.</h2><p>Refresh when data.json is available.</p></article>';
        return;
    }
    renderHome();
    renderChat();
    await refreshRemote();
    renderHome();
}

init();
