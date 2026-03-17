// ============================================================
// Peasant Simulator: Tavern Edition -- Browser Client
// ============================================================

// --- DOM Element References ---
const titleScreen    = document.getElementById('title-screen');
const newGameBtn     = document.getElementById('new-game-btn');
const nameInputArea  = document.getElementById('name-input-area');
const nameInput      = document.getElementById('name-input');
const nameSubmitBtn  = document.getElementById('name-submit-btn');
const loadingScreen  = document.getElementById('loading-screen');
const loadingSpinner = document.getElementById('loading-spinner');
const loadingText    = document.getElementById('loading-text');
const loadingBar     = document.getElementById('loading-bar');
const gameLayout     = document.getElementById('game-layout');
const textWindow     = document.getElementById('text-window');
const sidePanel      = document.getElementById('side-panel');
const inputBar       = document.getElementById('input-bar');
const cmdInput       = document.getElementById('cmd-input');
const disconnectOverlay = document.getElementById('disconnect-overlay');
const reconnectBtn   = document.getElementById('reconnect-btn');
const continueBtn    = document.getElementById('continue-btn');
const overwriteConfirm  = document.getElementById('overwrite-confirm');
const overwriteYesBtn   = document.getElementById('overwrite-yes-btn');
const overwriteNoBtn    = document.getElementById('overwrite-no-btn');

// Portrait banner elements
const portraitBanner = document.getElementById('portrait-banner');
const portraitImg    = document.getElementById('portrait-img');
const portraitName   = document.getElementById('portrait-name');

// Loading and audio elements
const loadingTip     = document.getElementById('loading-tip');
const muteToggle     = document.getElementById('mute-toggle');

// Guide modal elements
const guideModal     = document.getElementById('guide-modal');
const guideBtn       = document.getElementById('guide-btn');
const guideCloseBtn  = document.getElementById('guide-close-btn');
const guideHelpBtn   = document.getElementById('guide-help-btn');

// Lightbox elements
const lightbox         = document.getElementById('lightbox');
const lightboxImg      = document.getElementById('lightbox-img');
const lightboxCloseBtn = document.getElementById('lightbox-close-btn');

// Side panel stat elements
const statName         = document.getElementById('stat-name');
const statDrunkMeter   = document.getElementById('stat-drunk-meter');
const statMoney        = document.getElementById('stat-money');
const statInventory    = document.getElementById('stat-inventory');
const statInteractions = document.getElementById('stat-interactions');


// --- Session ID Persistence ---
let sessionId = sessionStorage.getItem('sessionId');
if (!sessionId) {
    sessionId = crypto.randomUUID();
    sessionStorage.setItem('sessionId', sessionId);
}

let ws = null;
let spinnerInterval = null;
const SPINNER_FRAMES = ['|', '/', '-', '\\'];
let spinnerIdx = 0;

// Typewriter animation state
const typewriterQueue = [];
let isTyping = false;
const TYPE_SPEED_MS = 50; // 40-60ms per character (user decision: 50ms)
let currentTypeInterval = null;

// Save/load state
let hasSaveFile = false;
let loadingFromSave = false;

// Template tracking
let currentTemplateId = '';

// Banner state machine
const bannerState = {
    mode: 'none',
    tavernUrl: null,
    itemUrl: null,
    patronUrl: null,
    patronName: null,
};

// Audio state
let ambientAudio = null;
let audioMuted = false;
let audioStarted = false;  // True once audio has been triggered


// --- Save Check ---

async function checkForSave() {
    try {
        const response = await fetch('/api/save-check');
        if (!response.ok) return false;
        const data = await response.json();
        return data.has_save === true;
    } catch {
        return false;
    }
}


// --- WebSocket Connection ---

function connect() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    ws = new WebSocket(`${protocol}//${host}/ws/${sessionId}`);

    ws.onopen = () => {
        disconnectOverlay.style.display = 'none';
        console.log('[WS] Connected, session:', sessionId);
    };

    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        console.log('[WS] Received:', msg);
        const handler = messageHandlers[msg.type];
        if (handler) handler(msg);
    };

    ws.onclose = () => {
        console.log('[WS] Disconnected');
        disconnectOverlay.style.display = 'flex';
    };

    ws.onerror = (err) => {
        console.error('[WS] Error:', err);
    };
}


// --- Message Handlers ---

const messageHandlers = {
    connected: (msg) => {
        console.log('[WS] Server acknowledged session:', msg.session_id);
    },

    narration: (msg) => {
        enqueueTypewriter('msg-narration', msg.text);
    },

    dialogue: (msg) => {
        enqueueTypewriter('msg-dialogue', msg.text, `[${msg.speaker}]: `);
    },

    player_echo: (msg) => {
        appendMessage('msg-player', '> ' + msg.text);
    },

    system: (msg) => {
        appendMessage('msg-system', msg.text);
    },

    divider: (msg) => {
        appendMessage('msg-divider', msg.text);
    },

    thinking: (msg) => {
        showThinking();
    },

    thinking_done: (msg) => {
        hideThinking();
        // Do NOT re-enable input here -- typewriter queue handles it.
        // Fallback: if no typewriter messages arrive, re-enable after short delay.
        setTimeout(() => {
            if (!isTyping && typewriterQueue.length === 0) {
                cmdInput.disabled = false;
                cmdInput.focus();
            }
        }, 200);
    },

    save_confirm: (msg) => {
        appendMessage('msg-system', '[System]: Game saved.');
    },

    status: (msg) => {
        updateStatus(msg);
        // Update banner state from STATUS fields
        if (msg.tavern_image_path) bannerState.tavernUrl = msg.tavern_image_path;
        if (msg.portrait_path) {
            bannerState.patronUrl = msg.portrait_path;
            bannerState.patronName = msg.active_patron || '';
            if (bannerState.mode !== 'item') bannerState.mode = 'patron';
        } else if (bannerState.mode !== 'item') {
            bannerState.mode = bannerState.tavernUrl ? 'tavern' : 'none';
        }
        applyBannerState();
        updateDrunkEffects(msg.tier || 0);
        if (msg.template_id) {
            currentTemplateId = msg.template_id;
        }
        // Start ambient audio if game is active but audio hasn't started yet
        if (msg.template_id && !audioStarted && document.body.classList.contains('game-mode')) {
            startAmbientAudio(msg.template_id);
        }
        if (loadingFromSave) {
            loadingFromSave = false;
            hideLoadingScreen();
        }
    },

    image: (msg) => {
        if (msg.image_path) {
            bannerState.itemUrl = msg.image_path;
            bannerState.mode = 'item';
            applyBannerState();
        }
    },

    loading_start: (msg) => {
        showLoadingScreen(msg.message || 'Loading...');
    },

    loading_progress: (msg) => {
        updateLoadingProgress(msg.step, msg.percent);
    },

    loading_complete: (msg) => {
        hideLoadingScreen();
    },

    game_over: (msg) => {
        // Game ended (quit or pass-out) -- show message, disable input
        if (msg.text) {
            appendMessage('msg-narration', msg.text);
        }
        appendMessage('msg-system', '--- Session ended. Refresh to play again. ---');
        cmdInput.disabled = true;
        // Fade out ambient audio
        if (ambientAudio && !ambientAudio.paused) {
            fadeOutAudio(ambientAudio, 2000);
            audioStarted = false;
        }
    },

    echo: (msg) => {
        console.log('[WS] Echo test:', msg.original);
    },

    error: (msg) => {
        console.error('[WS] Server error:', msg.text);
        appendMessage('msg-system', '[Error] ' + msg.text);
    },
};


// --- UI Functions ---

function appendMessage(className, text) {
    // If typewriter is active, queue this message to appear after current animation
    if (isTyping || typewriterQueue.length > 0) {
        typewriterQueue.push({ className, text, speakerHtml: null, instant: true });
        return;
    }
    _appendMessageNow(className, text);
}

function _appendMessageNow(className, text) {
    const div = document.createElement('div');
    div.className = className;
    div.textContent = text;
    textWindow.appendChild(div);
    autoScroll();
}

function autoScroll() {
    // Only auto-scroll if user is near the bottom (within 100px)
    // This prevents hijacking scroll when player is reading history
    const threshold = 100;
    const isNearBottom = textWindow.scrollHeight - textWindow.scrollTop - textWindow.clientHeight < threshold;
    if (isNearBottom) {
        textWindow.scrollTop = textWindow.scrollHeight;
    }
}


// --- Typewriter Animation Queue ---

let currentTypeDiv = null;
let currentTypeText = '';
let currentTypeIndex = 0;
let currentTypeCursor = null;

function enqueueTypewriter(className, text, speakerHtml) {
    typewriterQueue.push({ className, text, speakerHtml: speakerHtml || null });
    if (!isTyping) {
        processNextInQueue();
    }
}

function processNextInQueue() {
    if (typewriterQueue.length === 0) {
        isTyping = false;
        currentTypeDiv = null;
        cmdInput.disabled = false;
        cmdInput.focus();
        return;
    }

    const item = typewriterQueue.shift();

    // Handle instant (non-animated) messages queued behind typewriter
    if (item.instant) {
        _appendMessageNow(item.className, item.text);
        processNextInQueue();
        return;
    }

    isTyping = true;
    cmdInput.disabled = true;

    currentTypeDiv = document.createElement('div');
    currentTypeDiv.className = item.className;

    // If speakerHtml is provided, prepend speaker span
    if (item.speakerHtml) {
        const speakerSpan = document.createElement('span');
        speakerSpan.className = 'speaker';
        speakerSpan.textContent = item.speakerHtml;
        currentTypeDiv.appendChild(speakerSpan);
    }

    // Create blinking cursor
    currentTypeCursor = document.createElement('span');
    currentTypeCursor.className = 'typewriter-cursor';
    currentTypeCursor.textContent = '\u2588';
    currentTypeDiv.appendChild(currentTypeCursor);

    textWindow.appendChild(currentTypeDiv);
    autoScroll();

    // Set up character-by-character animation
    currentTypeText = item.text;
    currentTypeIndex = 0;

    currentTypeInterval = setInterval(() => {
        if (currentTypeIndex < currentTypeText.length) {
            // Insert character as text node before cursor
            const charNode = document.createTextNode(currentTypeText[currentTypeIndex]);
            currentTypeDiv.insertBefore(charNode, currentTypeCursor);
            currentTypeIndex++;
            autoScroll();
        } else {
            // All characters typed -- done
            clearInterval(currentTypeInterval);
            currentTypeInterval = null;
            if (currentTypeCursor && currentTypeCursor.parentNode) {
                currentTypeCursor.remove();
            }
            currentTypeCursor = null;
            processNextInQueue();
        }
    }, TYPE_SPEED_MS);
}

function skipCurrentMessage() {
    if (!isTyping) return;

    // Stop the interval
    if (currentTypeInterval) {
        clearInterval(currentTypeInterval);
        currentTypeInterval = null;
    }

    // Remove cursor
    if (currentTypeCursor && currentTypeCursor.parentNode) {
        currentTypeCursor.remove();
    }
    currentTypeCursor = null;

    // Reveal remaining text at once
    if (currentTypeDiv && currentTypeIndex < currentTypeText.length) {
        const remaining = currentTypeText.substring(currentTypeIndex);
        currentTypeDiv.appendChild(document.createTextNode(remaining));
    }

    // Continue to next in queue
    processNextInQueue();
}

// --- Skip Typewriter on Click/Keypress ---

document.addEventListener('keydown', (e) => {
    // If guide is open, let the guide's own Escape handler deal with it
    if (guideModal.classList.contains('visible')) return;
    // If lightbox is open, let the lightbox's own Escape handler deal with it
    if (lightbox.classList.contains('visible')) return;
    if (isTyping) {
        // Do NOT intercept Enter on cmd-input (let existing handler run)
        if (e.target === cmdInput && e.key === 'Enter') return;
        skipCurrentMessage();
        e.preventDefault();
        return;
    }
});

document.addEventListener('click', (e) => {
    if (isTyping) {
        // Don't skip if clicking on interactive elements
        if (e.target === cmdInput || e.target.id === 'mute-toggle' || e.target.id === 'guide-help-btn') return;
        // Don't skip if clicking inside the lightbox
        if (e.target.closest('#lightbox')) return;
        skipCurrentMessage();
    }
});


// --- Thinking Indicator ---

let thinkingEl = null;
let thinkingDots = 0;
let thinkingInterval = null;

function showThinking() {
    thinkingEl = document.createElement('div');
    thinkingEl.className = 'msg-thinking';
    thinkingEl.textContent = '...';
    textWindow.appendChild(thinkingEl);
    autoScroll();

    thinkingDots = 0;
    thinkingInterval = setInterval(() => {
        thinkingDots = (thinkingDots + 1) % 4;
        if (thinkingEl) {
            thinkingEl.textContent = '.'.repeat(thinkingDots + 1);
        }
    }, 400);
}

function hideThinking() {
    if (thinkingInterval) {
        clearInterval(thinkingInterval);
        thinkingInterval = null;
    }
    if (thinkingEl) {
        thinkingEl.remove();
        thinkingEl = null;
    }
}


// --- Status Panel ---

function updateStatus(msg) {
    if (statName) statName.textContent = msg.player_name || '';
    if (statDrunkMeter) statDrunkMeter.textContent = msg.drunk_meter || '';
    if (statMoney) statMoney.textContent = msg.money !== null && msg.money !== undefined
        ? `Gold: ${msg.money}`
        : 'Gold: --';
    if (statInventory) statInventory.textContent = msg.inventory && msg.inventory.length > 0
        ? msg.inventory.join(', ')
        : 'Empty';
    if (statInteractions) statInteractions.textContent = 'Interactions: ' + (msg.interactions || 0);
}


// --- Drunkenness Visual Effects ---

function updateDrunkEffects(tier) {
    const tw = document.getElementById('text-window');
    // Remove all drunk classes
    tw.classList.remove('drunk-1', 'drunk-2', 'drunk-3', 'drunk-4');
    // Apply current tier (0 = no class = no effect)
    if (tier >= 1 && tier <= 4) {
        tw.classList.add('drunk-' + tier);
    }
}


// --- Portrait Banner State Machine ---

function applyBannerState() {
    if (bannerState.mode === 'patron' && bannerState.patronUrl) {
        portraitImg.src = bannerState.patronUrl;
        portraitName.textContent = bannerState.patronName || '';
        portraitImg.classList.remove('tavern-mode');
        portraitBanner.style.display = '';
        portraitBanner.classList.add('visible');
    } else if (bannerState.mode === 'item' && bannerState.itemUrl) {
        portraitImg.src = bannerState.itemUrl;
        portraitName.textContent = '';
        portraitImg.classList.remove('tavern-mode');
        portraitBanner.style.display = '';
        portraitBanner.classList.add('visible');
    } else if (bannerState.mode === 'tavern' && bannerState.tavernUrl) {
        portraitImg.src = bannerState.tavernUrl;
        portraitName.textContent = '';
        portraitImg.classList.add('tavern-mode');
        portraitBanner.style.display = '';
        portraitBanner.classList.add('visible');
    } else {
        portraitBanner.classList.remove('visible');
        portraitImg.src = '';
        portraitName.textContent = '';
        portraitImg.classList.remove('tavern-mode');
    }
}

// Set permanent onerror handler (set once at init, not inside applyBannerState)
portraitImg.onerror = () => { portraitBanner.classList.remove('visible'); };


// --- Ambient Audio Manager ---

function startAmbientAudio(templateId) {
    if (!templateId) return;

    // If same track already playing, do nothing
    if (ambientAudio && ambientAudio.dataset.templateId === templateId && !ambientAudio.paused) {
        return;
    }

    // If different track playing, crossfade
    if (ambientAudio && !ambientAudio.paused) {
        fadeOutAudio(ambientAudio, 2000);
    }

    var audio = new Audio('/static/audio/' + templateId + '_ambience.mp3');
    audio.loop = true;
    audio.volume = 0;
    audio.muted = audioMuted;
    audio.dataset.templateId = templateId;

    var playPromise = audio.play();
    if (playPromise !== undefined) {
        playPromise.catch(function(err) {
            console.warn('[Audio] Autoplay blocked:', err);
        });
    }

    // Fade in over 2.5 seconds
    fadeInAudio(audio, 2500);
    ambientAudio = audio;
    audioStarted = true;
}

function fadeInAudio(audio, durationMs) {
    var steps = 25;
    var stepMs = durationMs / steps;
    var volumeStep = 1.0 / steps;
    var currentStep = 0;
    var fadeInterval = setInterval(function() {
        currentStep++;
        audio.volume = Math.min(1.0, volumeStep * currentStep);
        if (currentStep >= steps) {
            clearInterval(fadeInterval);
        }
    }, stepMs);
}

function fadeOutAudio(audio, durationMs) {
    var startVolume = audio.volume;
    var steps = 25;
    var stepMs = durationMs / steps;
    var volumeStep = startVolume / steps;
    var currentStep = 0;
    var fadeInterval = setInterval(function() {
        currentStep++;
        audio.volume = Math.max(0, startVolume - volumeStep * currentStep);
        if (currentStep >= steps) {
            clearInterval(fadeInterval);
            audio.pause();
            audio.src = '';
        }
    }, stepMs);
}


// --- Loading Screen ---

function showLoadingScreen(message) {
    titleScreen.style.display = 'none';
    loadingScreen.classList.add('visible');
    loadingText.textContent = message;

    // Start ASCII spinner
    spinnerIdx = 0;
    spinnerInterval = setInterval(() => {
        spinnerIdx = (spinnerIdx + 1) % SPINNER_FRAMES.length;
        loadingSpinner.textContent = SPINNER_FRAMES[spinnerIdx];
    }, 150);

    // Start tip cycling
    startTipCycling();
}

function updateLoadingProgress(step, percent) {
    loadingText.textContent = step || '';

    // Build ASCII progress bar: [####------] XX%
    if (typeof percent === 'number') {
        const filled = Math.round(percent / 10);
        const empty = 10 - filled;
        loadingBar.textContent = '[' + '#'.repeat(filled) + '-'.repeat(empty) + '] ' + percent + '%';
    }
}

// --- Loading Tips ---

const LOADING_TIPS = [
    "Some patrons may refuse a game challenge based on their personality.",
    "Be careful about getting too drunk -- it affects what you can see.",
    "Try giving items to patrons to see how they react.",
    "Each tavern has unique items you can pick up and keep.",
    "Use 'examine' on anything that catches your eye.",
    "The barkeep knows things. Try asking about the patrons.",
    "Food and water sober you up. Water is free -- order some when things get blurry.",
    "Some patrons carry more gold than others. Choose your wagers wisely.",
    "Type 'look' to survey the tavern and see who's around.",
    "Every patron has likes and dislikes. Pay attention to their reactions.",
    "You can give gold directly to patrons. Some appreciate it more than others.",
    "Slash-prefixed commands like /look and /order work mid-conversation.",
];

let tipIndex = 0;
let tipInterval = null;

function startTipCycling() {
    if (!loadingTip) return;
    tipIndex = Math.floor(Math.random() * LOADING_TIPS.length);
    loadingTip.textContent = LOADING_TIPS[tipIndex];
    tipInterval = setInterval(() => {
        tipIndex = (tipIndex + 1) % LOADING_TIPS.length;
        loadingTip.textContent = LOADING_TIPS[tipIndex];
    }, 12000);
}

function stopTipCycling() {
    if (tipInterval) {
        clearInterval(tipInterval);
        tipInterval = null;
    }
}

function hideLoadingScreen() {
    if (spinnerInterval) {
        clearInterval(spinnerInterval);
        spinnerInterval = null;
    }
    stopTipCycling();
    loadingScreen.classList.remove('visible');
    loadingScreen.style.display = 'none';
    enterGameMode();
}


// --- Game Mode Transition ---

function enterGameMode() {
    document.body.classList.add('game-mode');
    cmdInput.disabled = false;
    cmdInput.focus();
    // Start ambient audio if we have a template ID and haven't started yet
    if (currentTemplateId && !audioStarted) {
        startAmbientAudio(currentTemplateId);
    }
}


// --- Input Handling ---

function sendCommand(text) {
    if (!text.trim() || cmdInput.disabled) return;
    if (bannerState.mode === 'item') {
        bannerState.mode = bannerState.tavernUrl ? 'tavern' : 'none';
        bannerState.itemUrl = null;
        applyBannerState();
    }
    cmdInput.disabled = true; // lock until thinking_done
    ws.send(JSON.stringify({ type: 'input', text: text.trim() }));
    cmdInput.value = '';
}

// Enter key submits command
document.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
        // Check if we're in name input mode
        if (nameInput === document.activeElement && nameInput.value.trim()) {
            submitName();
            return;
        }
        // Game mode: submit command
        if (cmdInput && !cmdInput.disabled && document.body.classList.contains('game-mode')) {
            const text = cmdInput.value;
            if (text.trim()) {
                sendCommand(text);
            }
        }
    }
});


// --- Guide Modal ---

function openGuide() {
    guideModal.classList.add('visible');
}

function closeGuide() {
    guideModal.classList.remove('visible');
}

guideBtn.addEventListener('click', openGuide);
guideCloseBtn.addEventListener('click', closeGuide);
guideHelpBtn.addEventListener('click', openGuide);

// Close guide on Escape key
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && guideModal.classList.contains('visible')) {
        closeGuide();
    }
});

// Close guide when clicking backdrop (outside content area)
guideModal.addEventListener('click', function(e) {
    if (e.target === guideModal) {
        closeGuide();
    }
});


// --- Lightbox ---

function openLightbox(src) {
    lightboxImg.src = src;
    lightbox.classList.add('visible');
}

function closeLightbox() {
    lightbox.classList.remove('visible');
    lightboxImg.src = '';
}

portraitImg.addEventListener('click', () => {
    if (portraitImg.src && portraitBanner.classList.contains('visible')) {
        openLightbox(portraitImg.src);
    }
});

lightboxCloseBtn.addEventListener('click', closeLightbox);

lightbox.addEventListener('click', (e) => {
    if (e.target === lightbox) closeLightbox();
});

document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && lightbox.classList.contains('visible')) {
        closeLightbox();
    }
});


// --- Startup Flow ---

// CONTINUE button: load saved game
continueBtn.addEventListener('click', () => {
    continueBtn.style.display = 'none';
    newGameBtn.style.display = 'none';
    // Show brief loading screen for continue flow
    showLoadingScreen('Returning to the tavern...');
    loadingFromSave = true;
    ws.send(JSON.stringify({ type: 'load' }));
});

// New Game button: check for save before proceeding
newGameBtn.addEventListener('click', () => {
    if (hasSaveFile) {
        // Show overwrite confirmation (blocks WS send until confirmed)
        newGameBtn.style.display = 'none';
        continueBtn.style.display = 'none';
        overwriteConfirm.style.display = 'block';
    } else {
        newGameBtn.style.display = 'none';
        nameInputArea.classList.add('visible');
        nameInput.focus();
    }
});

// Overwrite confirmation: Yes -- proceed to name input
overwriteYesBtn.addEventListener('click', () => {
    overwriteConfirm.style.display = 'none';
    nameInputArea.classList.add('visible');
    nameInput.focus();
});

// Overwrite confirmation: No -- return to button state
overwriteNoBtn.addEventListener('click', () => {
    overwriteConfirm.style.display = 'none';
    continueBtn.style.display = 'block';
    newGameBtn.style.display = 'block';
});

// Name submit button
nameSubmitBtn.addEventListener('click', () => {
    submitName();
});

function submitName() {
    const name = nameInput.value.trim();
    if (!name) {
        nameInput.focus();
        return;
    }
    // Send new_game message with player name
    ws.send(JSON.stringify({
        type: 'new_game',
        player_name: name,
    }));
    // Hide name input area (loading screen will show via loading_start message)
    nameInputArea.classList.remove('visible');
}


// --- Reconnect ---

reconnectBtn.addEventListener('click', () => {
    connect();
});


// --- Mute Toggle ---

muteToggle.addEventListener('click', function() {
    audioMuted = !audioMuted;
    if (ambientAudio) {
        ambientAudio.muted = audioMuted;
    }
    muteToggle.classList.toggle('muted', audioMuted);
});


// --- Initial Connection ---

(async () => {
    hasSaveFile = await checkForSave();
    if (hasSaveFile) {
        continueBtn.style.display = 'block';
    }
    connect();
})();
