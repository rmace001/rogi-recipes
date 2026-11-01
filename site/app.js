const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const STORAGE = {
  favorites: 'rogi-recipes:favorites',
  grocery: 'rogi-recipes:grocery',
  notes: 'rogi-recipes:notes',
  theme: 'rogi-recipes:theme',
  timers: 'rogi-recipes:timers',
};

const state = {
  catalog: null,
  query: '',
  category: 'All',
  status: 'all',
  favoritesOnly: false,
  favorites: new Set(readStorage(STORAGE.favorites, [])),
  grocery: readStorage(STORAGE.grocery, []),
  notes: readStorage(STORAGE.notes, {}),
  activeRecipe: null,
  scale: 1,
  cookIndex: 0,
  timers: readStorage(STORAGE.timers, []).filter(timer => timer.target > Date.now() - 3600000),
  installPrompt: null,
};

function readStorage(key, fallback) {
  try {
    const parsed = JSON.parse(localStorage.getItem(key));
    return parsed ?? fallback;
  } catch {
    return fallback;
  }
}

function writeStorage(key, value) {
  localStorage.setItem(key, JSON.stringify(value));
}

function escapeHTML(value = '') {
  return String(value).replace(/[&<>'"]/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
  })[character]);
}

function titleCase(value) {
  return value.replace(/(^|[\s-])\S/g, match => match.toUpperCase());
}

function showToast(message) {
  const toast = $('#toast');
  toast.textContent = message;
  toast.classList.add('is-visible');
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove('is-visible'), 2200);
}

function closeDialog(dialog) {
  if (dialog?.open) dialog.close();
}

function humanStatus(status) {
  return {
    complete: 'Complete recipe',
    'ingredients-only': 'Ingredients only',
    'method-only': 'Method / idea',
    reference: 'Cooking reference',
    limited: 'Limited detail',
  }[status] || titleCase(status);
}

async function loadCatalog() {
  try {
    const response = await fetch('./data/recipes.json');
    if (!response.ok) throw new Error(`Catalog request returned ${response.status}`);
    state.catalog = await response.json();
    initializeCatalog();
  } catch (error) {
    console.error(error);
    $('#quick-stats').textContent = 'The recipe catalog could not be loaded.';
    $('#recipe-grid').innerHTML = '<div class="empty-state"><h3>Kitchen closed for maintenance</h3><p>Please reload the page or try again when online.</p></div>';
  }
}

function initializeCatalog() {
  const videos = state.catalog.recipes.filter(recipe => recipe.badges.includes('source video')).length;
  const complete = state.catalog.recipes.filter(recipe => recipe.status === 'complete').length;
  $('#quick-stats').textContent = `${state.catalog.count} entries · ${complete} complete recipes · ${videos} source videos`;
  $('#catalog-revision').textContent = `Catalog ${state.catalog.sourceRevision}`;
  renderCategoryFilters();
  renderRecipes();
  renderGrocery();
  handleRoute();
}

function renderCategoryFilters() {
  const categories = ['All', ...state.catalog.categories];
  $('#category-filters').innerHTML = categories.map(category => `
    <button class="filter-chip${state.category === category ? ' is-active' : ''}" type="button" data-category="${escapeHTML(category)}" aria-pressed="${state.category === category}">
      ${escapeHTML(category)}
    </button>
  `).join('');
}

function filteredRecipes() {
  if (!state.catalog) return [];
  const terms = state.query.casefold ? state.query.casefold().split(/\s+/).filter(Boolean) : state.query.toLocaleLowerCase().split(/\s+/).filter(Boolean);
  return state.catalog.recipes.filter(recipe => {
    if (state.category !== 'All' && recipe.category !== state.category) return false;
    if (state.status !== 'all' && recipe.status !== state.status) return false;
    if (state.favoritesOnly && !state.favorites.has(recipe.id)) return false;
    return terms.every(term => recipe.searchText.includes(term));
  });
}

function recipeSummary(recipe) {
  if (recipe.ingredients.length) {
    return recipe.ingredients.slice(0, 3).map(item => item.text.replace(/^\d+[\d\s/¼½¾⅓⅔⅛⅜⅝⅞.-]*\s*/, '')).join(' · ');
  }
  return recipe.reference[0] || recipe.steps[0] || recipe.meta[0] || 'Open for details';
}

function renderRecipes() {
  const recipes = filteredRecipes();
  const grid = $('#recipe-grid');
  $('#result-count').textContent = `${recipes.length} ${recipes.length === 1 ? 'entry' : 'entries'}`;
  $('#empty-state').hidden = Boolean(recipes.length);
  grid.innerHTML = recipes.map(recipe => {
    const favorite = state.favorites.has(recipe.id);
    const source = recipe.source?.platform && recipe.source.platform !== 'web' ? titleCase(recipe.source.platform) : '';
    return `<article class="recipe-card">
      <div class="card-top">
        <span class="card-category">${escapeHTML(recipe.category)}</span>
        <button class="favorite-button${favorite ? ' is-favorite' : ''}" type="button" data-favorite="${escapeHTML(recipe.id)}" aria-label="${favorite ? 'Remove from' : 'Add to'} favorites" aria-pressed="${favorite}">${favorite ? '★' : '☆'}</button>
      </div>
      <button class="card-open" type="button" data-recipe="${escapeHTML(recipe.id)}">
        <h3>${escapeHTML(recipe.title)}</h3>
        <p class="card-summary">${escapeHTML(recipeSummary(recipe))}</p>
      </button>
      <div class="card-footer">
        <span><i class="status-dot"></i>${escapeHTML(humanStatus(recipe.status))}</span>
        ${source ? `<span>${escapeHTML(source)} video</span>` : ''}
      </div>
    </article>`;
  }).join('');
}

function toggleFavorite(id) {
  if (state.favorites.has(id)) state.favorites.delete(id);
  else state.favorites.add(id);
  writeStorage(STORAGE.favorites, [...state.favorites]);
  renderRecipes();
  if (state.activeRecipe?.id === id) renderRecipeDetail(state.activeRecipe);
}

function groupIngredients(ingredients) {
  const groups = new Map();
  ingredients.forEach(item => {
    if (!groups.has(item.group)) groups.set(item.group, []);
    groups.get(item.group).push(item);
  });
  return groups;
}

const UNICODE_FRACTIONS = {
  '¼': .25, '½': .5, '¾': .75, '⅓': 1 / 3, '⅔': 2 / 3,
  '⅛': .125, '⅜': .375, '⅝': .625, '⅞': .875,
};

function parseLeadingQuantity(text) {
  const mixedUnicode = text.match(/^(\d+)\s*([¼½¾⅓⅔⅛⅜⅝⅞])\s*/);
  if (mixedUnicode) return { value: Number(mixedUnicode[1]) + UNICODE_FRACTIONS[mixedUnicode[2]], length: mixedUnicode[0].length };
  const unicode = text.match(/^([¼½¾⅓⅔⅛⅜⅝⅞])\s*/);
  if (unicode) return { value: UNICODE_FRACTIONS[unicode[1]], length: unicode[0].length };
  const mixed = text.match(/^(\d+)\s+(\d+)\/(\d+)\s*/);
  if (mixed) return { value: Number(mixed[1]) + Number(mixed[2]) / Number(mixed[3]), length: mixed[0].length };
  const fraction = text.match(/^(\d+)\/(\d+)\s*/);
  if (fraction) return { value: Number(fraction[1]) / Number(fraction[2]), length: fraction[0].length };
  const decimal = text.match(/^(\d+(?:\.\d+)?)\s*/);
  if (decimal) return { value: Number(decimal[1]), length: decimal[0].length };
  return null;
}

function formatQuantity(value) {
  const rounded = Math.round(value * 24) / 24;
  const whole = Math.floor(rounded + 1e-8);
  const fraction = rounded - whole;
  const options = [
    [1 / 8, '⅛'], [1 / 4, '¼'], [1 / 3, '⅓'], [3 / 8, '⅜'],
    [1 / 2, '½'], [5 / 8, '⅝'], [2 / 3, '⅔'], [3 / 4, '¾'], [7 / 8, '⅞'],
  ];
  const closest = options.reduce((best, option) => Math.abs(option[0] - fraction) < Math.abs(best[0] - fraction) ? option : best, [0, '']);
  if (Math.abs(closest[0] - fraction) < .025) return `${whole || ''}${whole && closest[1] ? ' ' : ''}${closest[1]}` || '0';
  return Number(rounded.toFixed(2)).toString();
}

function scaleIngredient(text) {
  if (state.scale === 1) return text;
  const parsed = parseLeadingQuantity(text);
  if (!parsed) return text;
  return `${formatQuantity(parsed.value * state.scale)} ${text.slice(parsed.length)}`.trim();
}

function servingsNumber(recipe) {
  const match = recipe.servings?.match(/\d+(?:\.\d+)?/);
  return match ? Number(match[0]) : null;
}

function parseDuration(step) {
  const matches = [...step.matchAll(/(\d+)\s*(?:[–—-]\s*\d+\s*)?(hours?|hrs?|minutes?|mins?|seconds?|secs?)\b/gi)];
  if (!matches.length) return null;
  const match = matches[0];
  const amount = Number(match[1]);
  const unit = match[2].toLowerCase();
  const seconds = unit.startsWith('h') ? amount * 3600 : unit.startsWith('m') ? amount * 60 : amount;
  return { seconds, label: `${amount} ${unit.startsWith('h') ? 'hr' : unit.startsWith('m') ? 'min' : 'sec'}` };
}

function sourceEmbed(source) {
  if (!source?.url) return null;
  try {
    const url = new URL(source.url);
    if (source.platform === 'youtube') {
      const id = url.hostname.includes('youtu.be') ? url.pathname.split('/').filter(Boolean)[0] : url.searchParams.get('v') || url.pathname.match(/\/(?:shorts|embed)\/([^/?]+)/)?.[1];
      return id ? `https://www.youtube-nocookie.com/embed/${encodeURIComponent(id)}` : null;
    }
    if (source.platform === 'instagram') {
      const match = url.pathname.match(/^\/(?:reel|p|tv)\/([^/]+)/);
      return match ? `https://www.instagram.com/p/${encodeURIComponent(match[1])}/embed/captioned/` : null;
    }
    if (source.platform === 'tiktok') {
      const id = url.pathname.match(/\/video\/(\d+)/)?.[1];
      return id ? `https://www.tiktok.com/player/v1/${id}?autoplay=0` : null;
    }
  } catch {
    return null;
  }
  return null;
}

function renderIngredientGroups(recipe) {
  const groups = groupIngredients(recipe.ingredients);
  return [...groups.entries()].map(([group, items]) => `
    ${groups.size > 1 || group !== 'Main' ? `<p class="ingredient-group">${escapeHTML(group)}</p>` : ''}
    <div class="ingredient-list">
      ${items.map((item, index) => `<label class="check-row"><input type="checkbox" data-ingredient-check="${index}"><span>${escapeHTML(scaleIngredient(item.text))}</span></label>`).join('')}
    </div>
  `).join('');
}

function renderRecipeDetail(recipe) {
  state.activeRecipe = recipe;
  const favorite = state.favorites.has(recipe.id);
  const baseServings = servingsNumber(recipe);
  const currentServings = baseServings ? formatQuantity(baseServings * state.scale) : null;
  const embed = sourceEmbed(recipe.source);
  const sourceCard = recipe.source ? `<div class="source-card">
    <strong>${escapeHTML(recipe.source.label || 'Original source')}</strong>
    ${recipe.source.url ? `<p><a href="${escapeHTML(recipe.source.url)}" target="_blank" rel="noopener noreferrer">Open original ${escapeHTML(recipe.source.platform || 'source')} ↗</a></p>` : ''}
  </div>` : '';
  const meta = [...new Set([...recipe.meta, ...recipe.nutrition])];
  const methodItems = recipe.steps.length ? recipe.steps : recipe.reference;
  const hasCookMode = methodItems.length > 0;

  $('#recipe-detail').innerHTML = `
    <header class="detail-hero">
      <p class="eyebrow">${escapeHTML(recipe.category)}</p>
      <h2>${escapeHTML(recipe.title)}</h2>
      <div class="detail-badges">${recipe.badges.map(badge => `<span class="badge">${escapeHTML(titleCase(badge))}</span>`).join('')}</div>
      <div class="detail-actions">
        ${hasCookMode ? '<button class="primary-button" type="button" data-cook>Start kitchen mode</button>' : ''}
        ${recipe.ingredients.length ? '<button class="secondary-button" type="button" data-add-grocery>Add to grocery list</button>' : ''}
        <button class="secondary-button" type="button" data-favorite="${escapeHTML(recipe.id)}">${favorite ? '★ Saved' : '☆ Save'}</button>
        <button class="secondary-button" type="button" data-share>Share</button>
        <button class="secondary-button" type="button" data-print>Print</button>
      </div>
    </header>
    <div class="detail-grid">
      <div class="detail-column">
        ${embed ? `<div class="video-facade" data-video-facade>
          <div><p class="eyebrow">Source video</p><h3>Watch the original technique</h3><p>Loads ${escapeHTML(titleCase(recipe.source.platform))} only when you choose.</p><br><button type="button" data-load-video>▶ Load video</button></div>
        </div>` : ''}
        ${sourceCard}
        ${meta.length ? `<section class="detail-section"><h3>At a glance</h3><ul class="note-list">${meta.map(item => `<li>${escapeHTML(item)}</li>`).join('')}</ul></section>` : ''}
        ${recipe.ingredients.length ? `<section class="detail-section">
          <h3>Ingredients</h3>
          ${baseServings ? `<div class="scaler"><button type="button" data-scale="down" aria-label="Decrease servings">−</button><strong>${escapeHTML(currentServings)} servings</strong><button type="button" data-scale="up" aria-label="Increase servings">+</button></div>` : ''}
          ${renderIngredientGroups(recipe)}
        </section>` : ''}
        ${recipe.useWith.length ? `<section class="detail-section"><h3>Use with</h3><div class="detail-badges">${recipe.useWith.map(item => `<span class="badge" style="color:var(--ink);border-color:var(--line);background:var(--surface-2)">${escapeHTML(item)}</span>`).join('')}</div></section>` : ''}
      </div>
      <div class="detail-column">
        ${methodItems.length ? `<section class="detail-section"><h3>${recipe.steps.length ? 'Method' : 'Reference'}</h3><ol class="step-list">${methodItems.map((step, index) => {
          const duration = parseDuration(step);
          return `<li class="step-row"><span class="step-number">${index + 1}</span><span>${escapeHTML(step)}</span>${duration ? `<button class="timer-button" type="button" data-timer="${duration.seconds}" data-timer-label="${escapeHTML(recipe.title)}">⏱ ${escapeHTML(duration.label)}</button>` : ''}</li>`;
        }).join('')}</ol></section>` : ''}
        ${recipe.notes.length ? `<section class="detail-section"><h3>Notes</h3><ul class="note-list">${recipe.notes.map(note => `<li>${escapeHTML(note)}</li>`).join('')}</ul></section>` : ''}
        <section class="detail-section"><h3>Your kitchen note</h3><p class="muted">Stored only in this browser.</p><textarea class="personal-note" data-note placeholder="What would you change next time?">${escapeHTML(state.notes[recipe.id] || '')}</textarea></section>
      </div>
    </div>`;
}

function openRecipe(id, updateHash = true) {
  const recipe = state.catalog?.recipes.find(item => item.id === id);
  if (!recipe) return;
  state.scale = 1;
  renderRecipeDetail(recipe);
  const dialog = $('#recipe-dialog');
  if (!dialog.open) dialog.showModal();
  if (updateHash) history.pushState(null, '', `#recipe/${encodeURIComponent(id)}`);
}

function addRecipeToGrocery(recipe) {
  const existing = new Set(state.grocery.map(item => `${item.text.toLocaleLowerCase()}|${item.recipeId}`));
  recipe.ingredients.forEach(ingredient => {
    const text = scaleIngredient(ingredient.text);
    const key = `${text.toLocaleLowerCase()}|${recipe.id}`;
    if (!existing.has(key)) {
      state.grocery.push({ id: crypto.randomUUID(), text, recipeId: recipe.id, recipeTitle: recipe.title, checked: false });
      existing.add(key);
    }
  });
  writeStorage(STORAGE.grocery, state.grocery);
  renderGrocery();
  showToast(`${recipe.ingredients.length} ingredients added`);
}

function renderGrocery() {
  $('#grocery-count').textContent = state.grocery.length;
  const list = $('#grocery-list');
  if (!list) return;
  if (!state.grocery.length) {
    list.innerHTML = '<div class="grocery-empty"><h3>Your list is empty</h3><p class="muted">Open a recipe and add its ingredients.</p></div>';
    return;
  }
  const sorted = [...state.grocery].sort((a, b) => Number(a.checked) - Number(b.checked) || a.recipeTitle.localeCompare(b.recipeTitle));
  list.innerHTML = sorted.map(item => `<div class="grocery-row">
    <input type="checkbox" id="grocery-${escapeHTML(item.id)}" data-grocery-check="${escapeHTML(item.id)}" ${item.checked ? 'checked' : ''}>
    <label for="grocery-${escapeHTML(item.id)}"><strong>${escapeHTML(item.text)}</strong><br><small class="muted">${escapeHTML(item.recipeTitle)}</small></label>
    <button class="remove-item" type="button" data-grocery-remove="${escapeHTML(item.id)}" aria-label="Remove ${escapeHTML(item.text)}">×</button>
  </div>`).join('');
}

function openGrocery() {
  renderGrocery();
  $('#grocery-dialog').showModal();
}

function buildMeal() {
  const choose = category => {
    const matches = state.catalog.recipes.filter(recipe => recipe.category === category);
    return matches[Math.floor(Math.random() * matches.length)];
  };
  const meal = [
    ['Main', choose('Mains') || choose('Bowls & Salads')],
    ['Sauce or dressing', choose('Sauces & Dressings')],
    ['Side or component', choose('Sides & Components')],
  ];
  $('#meal-builder').innerHTML = meal.map(([label, recipe]) => `<div class="meal-slot"><span>${escapeHTML(label)}</span><button type="button" data-meal-recipe="${escapeHTML(recipe.id)}">${escapeHTML(recipe.title)} →</button></div>`).join('');
}

function openMealBuilder() {
  buildMeal();
  $('#meal-builder-dialog').showModal();
}

function openCookMode() {
  if (!state.activeRecipe) return;
  state.cookIndex = 0;
  $('#cook-title').textContent = state.activeRecipe.title;
  renderCookStep();
  closeDialog($('#recipe-dialog'));
  $('#cook-dialog').showModal();
  try { navigator.wakeLock?.request('screen').then(lock => { state.wakeLock = lock; }); } catch { /* wake lock is optional */ }
}

function renderCookStep() {
  const items = state.activeRecipe.steps.length ? state.activeRecipe.steps : state.activeRecipe.reference;
  const step = items[state.cookIndex];
  const duration = parseDuration(step);
  $('#cook-step').innerHTML = `<div><p>${escapeHTML(step)}</p>${duration ? `<button class="timer-button" type="button" data-timer="${duration.seconds}" data-timer-label="${escapeHTML(state.activeRecipe.title)}">⏱ Start ${escapeHTML(duration.label)} timer</button>` : ''}</div>`;
  $('#cook-counter').textContent = `Step ${state.cookIndex + 1} of ${items.length}`;
  $('#cook-progress-bar').style.width = `${((state.cookIndex + 1) / items.length) * 100}%`;
  $('#cook-previous').disabled = state.cookIndex === 0;
  $('#cook-next').textContent = state.cookIndex === items.length - 1 ? 'Finish ✓' : 'Next →';
}

function exitCookMode() {
  closeDialog($('#cook-dialog'));
  state.wakeLock?.release();
  state.wakeLock = null;
  if (state.activeRecipe) $('#recipe-dialog').showModal();
}

function startTimer(seconds, label) {
  state.timers.push({ id: crypto.randomUUID(), target: Date.now() + seconds * 1000, label });
  writeStorage(STORAGE.timers, state.timers);
  renderTimers();
  showToast('Timer started');
}

function formatTime(milliseconds) {
  const total = Math.max(0, Math.ceil(milliseconds / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}` : `${minutes}:${String(seconds).padStart(2, '0')}`;
}

function renderTimers() {
  const now = Date.now();
  $('#timer-rack').innerHTML = state.timers.map(timer => `<div class="active-timer${timer.target <= now ? ' is-done' : ''}">
    <div><strong>${escapeHTML(timer.target <= now ? 'Time is up!' : formatTime(timer.target - now))}</strong><small>${escapeHTML(timer.label)}</small></div>
    <button type="button" data-timer-remove="${escapeHTML(timer.id)}" aria-label="Dismiss timer">×</button>
  </div>`).join('');
}

async function shareRecipe() {
  const url = new URL(`#recipe/${encodeURIComponent(state.activeRecipe.id)}`, location.href);
  const data = { title: state.activeRecipe.title, text: `Cook ${state.activeRecipe.title}`, url: url.href };
  try {
    if (navigator.share) await navigator.share(data);
    else {
      await navigator.clipboard.writeText(url.href);
      showToast('Recipe link copied');
    }
  } catch (error) {
    if (error.name !== 'AbortError') showToast('Could not share this recipe');
  }
}

function loadVideo() {
  const embed = sourceEmbed(state.activeRecipe.source);
  if (!embed) return;
  const facade = $('[data-video-facade]');
  const iframe = document.createElement('iframe');
  iframe.className = 'video-frame';
  iframe.src = embed;
  iframe.title = `${state.activeRecipe.title} source video`;
  iframe.loading = 'lazy';
  iframe.allow = 'accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share';
  iframe.allowFullscreen = true;
  facade.replaceWith(iframe);
}

function handleRoute() {
  if (!state.catalog) return;
  const match = location.hash.match(/^#recipe\/(.+)$/);
  if (match) openRecipe(decodeURIComponent(match[1]), false);
  else closeDialog($('#recipe-dialog'));
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  writeStorage(STORAGE.theme, theme);
}

function initializeTheme() {
  const saved = localStorage.getItem(STORAGE.theme)?.replaceAll('"', '');
  applyTheme(saved || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'));
}

function clearFilters() {
  state.query = '';
  state.category = 'All';
  state.status = 'all';
  state.favoritesOnly = false;
  $('#recipe-search').value = '';
  $('#status-filter').value = 'all';
  $('#favorites-filter').checked = false;
  renderCategoryFilters();
  renderRecipes();
}

function bindEvents() {
  document.addEventListener('click', event => {
    const recipeButton = event.target.closest('[data-recipe]');
    const favoriteButton = event.target.closest('[data-favorite]');
    const categoryButton = event.target.closest('[data-category]');
    const timerButton = event.target.closest('[data-timer]');
    if (recipeButton) openRecipe(recipeButton.dataset.recipe);
    if (favoriteButton) {
      event.stopPropagation();
      toggleFavorite(favoriteButton.dataset.favorite);
    }
    if (categoryButton) {
      state.category = categoryButton.dataset.category;
      renderCategoryFilters();
      renderRecipes();
    }
    if (timerButton) startTimer(Number(timerButton.dataset.timer), timerButton.dataset.timerLabel);
    if (event.target.closest('[data-add-grocery]')) addRecipeToGrocery(state.activeRecipe);
    if (event.target.closest('[data-cook]')) openCookMode();
    if (event.target.closest('[data-share]')) shareRecipe();
    if (event.target.closest('[data-print]')) window.print();
    if (event.target.closest('[data-load-video]')) loadVideo();
    if (event.target.closest('[data-close-dialog]')) closeDialog(event.target.closest('dialog'));
    if (event.target.closest('[data-close-cook]')) exitCookMode();
    if (event.target.closest('[data-open="grocery"]')) openGrocery();
    if (event.target.closest('[data-open="meal-builder"]')) openMealBuilder();
    const mealRecipe = event.target.closest('[data-meal-recipe]');
    if (mealRecipe) {
      closeDialog($('#meal-builder-dialog'));
      openRecipe(mealRecipe.dataset.mealRecipe);
    }
    const scale = event.target.closest('[data-scale]');
    if (scale) {
      state.scale = scale.dataset.scale === 'up' ? Math.min(8, state.scale + .5) : Math.max(.5, state.scale - .5);
      renderRecipeDetail(state.activeRecipe);
    }
    const groceryRemove = event.target.closest('[data-grocery-remove]');
    if (groceryRemove) {
      state.grocery = state.grocery.filter(item => item.id !== groceryRemove.dataset.groceryRemove);
      writeStorage(STORAGE.grocery, state.grocery);
      renderGrocery();
    }
    const timerRemove = event.target.closest('[data-timer-remove]');
    if (timerRemove) {
      state.timers = state.timers.filter(item => item.id !== timerRemove.dataset.timerRemove);
      writeStorage(STORAGE.timers, state.timers);
      renderTimers();
    }
  });

  document.addEventListener('change', event => {
    if (event.target.matches('[data-grocery-check]')) {
      const item = state.grocery.find(entry => entry.id === event.target.dataset.groceryCheck);
      if (item) item.checked = event.target.checked;
      writeStorage(STORAGE.grocery, state.grocery);
      renderGrocery();
    }
  });

  document.addEventListener('input', event => {
    if (event.target.id === 'recipe-search') {
      state.query = event.target.value.toLocaleLowerCase();
      renderRecipes();
    }
    if (event.target.matches('[data-note]') && state.activeRecipe) {
      state.notes[state.activeRecipe.id] = event.target.value;
      writeStorage(STORAGE.notes, state.notes);
    }
  });

  $('#status-filter').addEventListener('change', event => { state.status = event.target.value; renderRecipes(); });
  $('#favorites-filter').addEventListener('change', event => { state.favoritesOnly = event.target.checked; renderRecipes(); });
  $('#clear-filters').addEventListener('click', clearFilters);
  $('#shuffle-meal').addEventListener('click', buildMeal);
  $('#clear-grocery').addEventListener('click', () => {
    if (!state.grocery.length || confirm('Clear the entire grocery list?')) {
      state.grocery = [];
      writeStorage(STORAGE.grocery, state.grocery);
      renderGrocery();
    }
  });
  $('#copy-grocery').addEventListener('click', async () => {
    const list = state.grocery.filter(item => !item.checked).map(item => `- [ ] ${item.text} — ${item.recipeTitle}`).join('\n');
    if (!list) return showToast('The grocery list is empty');
    await navigator.clipboard.writeText(list);
    showToast('Grocery list copied');
  });
  $('#theme-toggle').addEventListener('click', () => applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));
  $('#cook-previous').addEventListener('click', () => { state.cookIndex = Math.max(0, state.cookIndex - 1); renderCookStep(); });
  $('#cook-next').addEventListener('click', () => {
    const items = state.activeRecipe.steps.length ? state.activeRecipe.steps : state.activeRecipe.reference;
    if (state.cookIndex === items.length - 1) exitCookMode();
    else { state.cookIndex += 1; renderCookStep(); }
  });
  $('#recipe-dialog').addEventListener('close', () => {
    if (location.hash.startsWith('#recipe/')) history.replaceState(null, '', location.pathname + location.search);
  });
  window.addEventListener('hashchange', handleRoute);
  window.addEventListener('popstate', handleRoute);
  window.addEventListener('keydown', event => {
    if (event.key === '/' && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) {
      event.preventDefault();
      $('#recipe-search').focus();
    }
    if ($('#cook-dialog').open && event.key === 'ArrowRight') $('#cook-next').click();
    if ($('#cook-dialog').open && event.key === 'ArrowLeft') $('#cook-previous').click();
  });
  window.addEventListener('beforeinstallprompt', event => {
    event.preventDefault();
    state.installPrompt = event;
    $('#install-button').hidden = false;
  });
  $('#install-button').addEventListener('click', async () => {
    await state.installPrompt?.prompt();
    state.installPrompt = null;
    $('#install-button').hidden = true;
  });
}

initializeTheme();
bindEvents();
loadCatalog();
renderTimers();
setInterval(renderTimers, 1000);
writeStorage(STORAGE.timers, state.timers);

if ('serviceWorker' in navigator && location.protocol.startsWith('http')) {
  window.addEventListener('load', () => navigator.serviceWorker.register('./sw.js').catch(console.error));
}
