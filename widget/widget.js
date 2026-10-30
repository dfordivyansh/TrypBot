/**
 * TrypBot Widget - Production-ready embeddable chatbot widget
 * Modern premium design inspired by Intercom, Tidio, Crisp
 * 
 * Usage: <script src="https://trypbot.duckdns.org/widget/widget.js"></script>
 * 
 * @version 1.0.0
 * @author TrypBot
 */

(function() {
  'use strict';

  // ============================================
  // CONFIGURATION
  // ============================================
  
  // Default configuration - can be overridden by window.TrypBotConfig
  const DEFAULT_CONFIG = {
    primaryColor: '#EF4444',
    title: 'Trypdeals AI Assistant',
    apiBase: 'https://trypbot.duckdns.org',
    position: 'bottom-right',
    theme: 'light',
    autoOpen: true,
    welcomeMessage: 'Hello! I\'m here to help you plan your perfect trip. Please tell me which destination in India you\'d like to explore?',
    enableDarkMode: true,
    enableSound: false,
    enableEmoji: true
  };

  // Detect script URL to use as base for loading CSS and icons
  const scriptUrl = document.currentScript ? document.currentScript.src : '';
  // Extract base URL for static files - e.g., /api/widget/widget.js -> /api/widget
  const staticBase = scriptUrl ? scriptUrl.substring(0, scriptUrl.lastIndexOf('/')) : '';
  // Extract API base - e.g., http://127.0.0.1:8000/api/widget/widget.js -> http://127.0.0.1:8000
  let apiBaseFromScript = '';
  if (scriptUrl) {
    const urlObj = new URL(scriptUrl);
    apiBaseFromScript = `${urlObj.protocol}//${urlObj.host}`;
  }
  
  // Merge user configuration with defaults
  const config = Object.assign({}, DEFAULT_CONFIG, window.TrypBotConfig || {});
  
  // Use detected API base if still using default
  if (apiBaseFromScript && config.apiBase === 'https://trypbot.duckdns.org') {
    config.apiBase = apiBaseFromScript;
  }
  config.staticBase = staticBase || config.apiBase;

  // ============================================
  // STATE MANAGEMENT
  // ============================================
  
  const state = {
    isOpen: true,  // Always open by default
    isMinimized: false,
    isAutoOpening: false,
    justOpened: false,
    leadId: null,
    userName: null,
    userPhone: null,
    conversation: [],
    unreadCount: 0,
    isTyping: false,
    socket: null,
    theme: config.theme
  };

  // ============================================
  // LOCAL STORAGE KEYS
  // ============================================
  
  const STORAGE_KEYS = {
    LEAD_ID: 'trypbot_lead_id',
    USER_NAME: 'trypbot_user_name',
    USER_PHONE: 'trypbot_user_phone',
    CONVERSATION: 'trypbot_conversation',
    THEME: 'trypbot_theme'
  };

  // ============================================
  // DOM ELEMENTS
  // ============================================
  
  let elements = {};

  // ============================================
  // UTILITY FUNCTIONS
  // ============================================
  
  /**
   * Get value from localStorage
   * @param {string} key - Storage key
   * @returns {any} Stored value or null
   */
  function getFromStorage(key) {
    try {
      const value = localStorage.getItem(key);
      return value ? JSON.parse(value) : null;
    } catch (error) {
      console.error('TrypBot: Error reading from localStorage', error);
      return null;
    }
  }

  /**
   * Set value in localStorage
   * @param {string} key - Storage key
   * @param {any} value - Value to store
   */
  function setToStorage(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch (error) {
      console.error('TrypBot: Error writing to localStorage', error);
    }
  }

  /**
   * Remove value from localStorage
   * @param {string} key - Storage key
   */
  function removeFromStorage(key) {
    try {
      localStorage.removeItem(key);
    } catch (error) {
      console.error('TrypBot: Error removing from localStorage', error);
    }
  }

  /**
   * Clear all TrypBot data from localStorage
   */
  function clearStorage() {
    Object.values(STORAGE_KEYS).forEach(key => removeFromStorage(key));
  }

  /**
   * Validate Indian mobile number
   * @param {string} phone - Phone number to validate
   * @returns {boolean} True if valid
   */
  function validateIndianPhone(phone) {
    // Indian mobile numbers: 10 digits, starts with 6-9
    const indianPhoneRegex = /^[6-9]\d{9}$/;
    const cleanedPhone = phone.replace(/\D/g, '');
    return indianPhoneRegex.test(cleanedPhone);
  }

  /**
   * Format phone number for display
   * @param {string} phone - Phone number
   * @returns {string} Formatted phone number
   */
  function formatPhone(phone) {
    const cleaned = phone.replace(/\D/g, '');
    if (cleaned.length === 10) {
      return `+91 ${cleaned.slice(0, 5)} ${cleaned.slice(5)}`;
    }
    return phone;
  }

  /**
   * Get current page URL
   * @returns {string} Current page URL
   */
  function getCurrentUrl() {
    return window.location.href;
  }

  /**
   * Get browser information
   * @returns {string} Browser name and version
   */
  function getBrowserInfo() {
    const ua = navigator.userAgent;
    let browser = 'Unknown';
    
    if (ua.indexOf('Chrome') > -1) browser = 'Chrome';
    else if (ua.indexOf('Safari') > -1) browser = 'Safari';
    else if (ua.indexOf('Firefox') > -1) browser = 'Firefox';
    else if (ua.indexOf('Edge') > -1) browser = 'Edge';
    else if (ua.indexOf('Opera') > -1) browser = 'Opera';
    
    return browser;
  }

  /**
   * Get device information
   * @returns {string} Device type
   */
  function getDeviceInfo() {
    const width = window.innerWidth;
    if (width < 480) return 'Mobile';
    if (width < 768) return 'Tablet';
    return 'Desktop';
  }

  /**
   * Format timestamp
   * @param {Date} date - Date object
   * @returns {string} Formatted time
   */
  function formatTime(date) {
    const hours = date.getHours();
    const minutes = date.getMinutes().toString().padStart(2, '0');
    return `${hours}:${minutes}`;
  }

  /**
   * Escape HTML to prevent XSS
   * @param {string} text - Text to escape
   * @returns {string} Escaped text
   */
  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  /**
   * Debounce function
   * @param {Function} func - Function to debounce
   * @param {number} wait - Wait time in ms
   * @returns {Function} Debounced function
   */
  function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
      const later = () => {
        clearTimeout(timeout);
        func(...args);
      };
      clearTimeout(timeout);
      timeout = setTimeout(later, wait);
    };
  }

  // ============================================
  // API FUNCTIONS
  // ============================================
  
  /**
   * Create lead via API
   * @param {Object} data - Lead data
   * @returns {Promise<Object>} API response
   */
  async function createLead(data) {
    try {
      const response = await fetch(`${config.apiBase}/api/lead/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(data)
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('TrypBot: Error creating lead', error);
      throw error;
    }
  }

  /**
   * Update lead via API
   * @param {string} leadId - Lead ID
   * @param {Object} data - Updated lead data
   * @returns {Promise<Object>} API response
   */
  async function updateLead(leadId, data) {
    try {
      const response = await fetch(`${config.apiBase}/api/lead/${leadId}/`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(data)
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('TrypBot: Error updating lead', error);
      throw error;
    }
  }

  /**
   * Create lead with phone number and unique ID
   * @param {string} phone - User's phone number
   */
  async function createLeadWithPhone(phone) {
    try {
      // Generate unique ID for website lead
      const timestamp = Date.now();
      const randomSuffix = Math.floor(Math.random() * 10000);
      const uniqueId = `Website ${randomSuffix}`;

      const leadData = {
        name: uniqueId,
        phone: phone,
        source: 'website',
        page: getCurrentUrl(),
        browser: getBrowserInfo(),
        device: getDeviceInfo()
      };

      const response = await createLead(leadData);
      
      // Store lead data
      state.leadId = response.lead_id;
      state.userName = uniqueId;
      state.userPhone = phone;
      
      setToStorage(STORAGE_KEYS.LEAD_ID, state.leadId);
      setToStorage(STORAGE_KEYS.USER_NAME, state.userName);
      setToStorage(STORAGE_KEYS.USER_PHONE, state.userPhone);
      
      // Don't show chat screen here - let the caller handle it
      
      // Connect WebSocket
      connectSocket();
      
    } catch (error) {
      console.error('TrypBot: Error creating lead with phone', error);
      // Fallback to welcome screen if lead creation fails
      showWelcomeScreen();
    }
  }

  /**
   * Send message via API
   * @param {Object} data - Message data
   * @returns {Promise<Object>} API response
   */
  async function sendMessage(data) {
    try {
      const response = await fetch(`${config.apiBase}/api/chat/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(data)
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('TrypBot: Error sending message', error);
      throw error;
    }
  }

  // ============================================
  // WEBSOCKET FUNCTIONS (PREPARATION)
  // ============================================
  
  /**
   * Connect to WebSocket server
   * @returns {WebSocket} WebSocket connection
   */
  function connectSocket() {
    // WebSocket endpoint not implemented on backend - using HTTP only
    console.log('TrypBot: WebSocket not available, using HTTP polling');
    return null;
  }

  /**
   * Disconnect from WebSocket server
   */
  function disconnectSocket() {
    if (state.socket) {
      state.socket.close();
      state.socket = null;
    }
  }

  /**
   * Send message via WebSocket
   * @param {Object} data - Message data
   */
  function sendSocketMessage(data) {
    if (state.socket && state.socket.readyState === WebSocket.OPEN) {
      state.socket.send(JSON.stringify(data));
    } else {
      console.warn('TrypBot: WebSocket not connected, falling back to HTTP');
      sendMessage(data);
    }
  }

  /**
   * Handle incoming WebSocket message
   * @param {Object} data - Message data
   */
  function handleSocketMessage(data) {
    if (data.type === 'message') {
      addMessage(data.message, 'bot');
    } else if (data.type === 'typing') {
      setTypingIndicator(data.isTyping);
    }
  }

  // ============================================
  // DOM CREATION FUNCTIONS
  // ============================================
  
  /**
   * Create floating button element
   * @returns {HTMLElement} Floating button element
   */
  function createFloatingButton() {
    const button = document.createElement('button');
    button.className = 'trypbot-floating-button pulse';
    button.setAttribute('aria-label', 'Open chat');
    button.setAttribute('aria-expanded', 'false');
    button.setAttribute('role', 'button');
    button.tabIndex = 0;

    // Load SVG icon
    fetch(`${config.staticBase}/chat-icon.svg`)
      .then(response => response.text())
      .then(svg => {
        button.innerHTML = svg;
      })
      .catch(() => {
        // Fallback if SVG fails to load
        button.innerHTML = `
          <svg width="256px" height="256px" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg" fill="#ffffff" stroke="#ffffff" stroke-width="0.5">
            <path fill-rule="evenodd" clip-rule="evenodd" d="M8.48 4h4l.5.5v2.03h.52l.5.5V8l-.5.5h-.52v3l-.5.5H9.36l-2.5 2.76L6 14.4V12H3.5l-.5-.64V8.5h-.5L2 8v-.97l.5-.5H3V4.36L3.53 4h4V2.86A1 1 0 0 1 7 2a1 1 0 0 1 2 0 1 1 0 0 1-.52.83V4zM12 8V5H4v5.86l2.5.14H7v2.19l1.8-2.04.35-.15H12V8zm-2.12.51a2.71 2.71 0 0 1-1.37.74v-.01a2.71 2.71 0 0 1-2.42-.74l-.7.71c.34.34.745.608 1.19.79.45.188.932.286 1.42.29a3.7 3.7 0 0 0 2.58-1.07l-.7-.71zM6.49 6.5h-1v1h1v-1zm3 0h1v1h-1v-1z"></path>
          </svg>
        `;
      });

    // Online indicator
    const onlineIndicator = document.createElement('div');
    onlineIndicator.className = 'trypbot-online-indicator';
    button.appendChild(onlineIndicator);

    // Unread badge
    const unreadBadge = document.createElement('div');
    unreadBadge.className = 'trypbot-unread-badge';
    unreadBadge.setAttribute('aria-live', 'polite');
    button.appendChild(unreadBadge);

    return button;
  }

  /**
   * Create chat window element
   * @returns {HTMLElement} Chat window element
   */
  function createChatWindow() {
    const window = document.createElement('div');
    window.className = 'trypbot-chat-window';
    window.setAttribute('role', 'dialog');
    window.setAttribute('aria-label', 'Chat with TrypBot');
    window.setAttribute('aria-modal', 'true');

    // Header
    const header = createHeader();
    window.appendChild(header);

    // Content area
    const content = document.createElement('div');
    content.className = 'trypbot-content';
    window.appendChild(content);

    // Input area
    const inputArea = createInputArea();
    window.appendChild(inputArea);

    return window;
  }

  /**
   * Create header element
   * @returns {HTMLElement} Header element
   */
  function createHeader() {
    const header = document.createElement('div');
    header.className = 'trypbot-header';

    // Left side
    const left = document.createElement('div');
    left.className = 'trypbot-header-left';

    // Logo with SVG icon
    const logo = document.createElement('div');
    logo.className = 'trypbot-logo';
    logo.innerHTML = `
      <svg width="256px" height="256px" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg" fill="#ffffff" stroke="#ffffff" stroke-width="0.5">
        <path fill-rule="evenodd" clip-rule="evenodd" d="M8.48 4h4l.5.5v2.03h.52l.5.5V8l-.5.5h-.52v3l-.5.5H9.36l-2.5 2.76L6 14.4V12H3.5l-.5-.64V8.5h-.5L2 8v-.97l.5-.5H3V4.36L3.53 4h4V2.86A1 1 0 0 1 7 2a1 1 0 0 1 2 0 1 1 0 0 1-.52.83V4zM12 8V5H4v5.86l2.5.14H7v2.19l1.8-2.04.35-.15H12V8zm-2.12.51a2.71 2.71 0 0 1-1.37.74v-.01a2.71 2.71 0 0 1-2.42-.74l-.7.71c.34.34.745.608 1.19.79.45.188.932.286 1.42.29a3.7 3.7 0 0 0 2.58-1.07l-.7-.71zM6.49 6.5h-1v1h1v-1zm3 0h1v1h-1v-1z"></path>
      </svg>
    `;
    left.appendChild(logo);

    // Title
    const title = document.createElement('div');
    title.className = 'trypbot-title';

    const titleText = document.createElement('h3');
    titleText.textContent = config.title;
    title.appendChild(titleText);

    const status = document.createElement('div');
    status.className = 'trypbot-status';

    const statusDot = document.createElement('div');
    statusDot.className = 'trypbot-status-dot';
    status.appendChild(statusDot);

    const statusText = document.createElement('span');
    statusText.textContent = 'Online';
    status.appendChild(statusText);

    title.appendChild(status);
    left.appendChild(title);
    header.appendChild(left);

    // Right side
    const right = document.createElement('div');
    right.className = 'trypbot-header-right';

    // Close button
    const closeBtn = document.createElement('button');
    closeBtn.className = 'trypbot-header-button';
    closeBtn.setAttribute('aria-label', 'Close chat');
    closeBtn.innerHTML = `
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <line x1="18" y1="6" x2="6" y2="18"></line>
        <line x1="6" y1="6" x2="18" y2="18"></line>
      </svg>
    `;
    closeBtn.addEventListener('click', closeChat);
    right.appendChild(closeBtn);

    header.appendChild(right);

    return header;
  }

  /**
   * Create phone input screen element
   * @returns {HTMLElement} Phone input screen element
   */
  function createPhoneInputScreen() {
    const screen = document.createElement('div');
    screen.className = 'trypbot-welcome-screen';

    const title = document.createElement('h2');
    title.className = 'trypbot-welcome-title';
    title.textContent = 'Welcome!';
    screen.appendChild(title);

    const subtitle = document.createElement('p');
    subtitle.className = 'trypbot-welcome-subtitle';
    subtitle.textContent = "We're here to help you plan an amazing trip! Share your phone number and let's get started";
    screen.appendChild(subtitle);

    const form = document.createElement('div');
    form.className = 'trypbot-form';

    const formGroup = document.createElement('div');
    formGroup.className = 'trypbot-form-group';

    const label = document.createElement('label');
    label.className = 'trypbot-form-label';
    label.textContent = 'Phone Number';
    label.setAttribute('for', 'trypbot-phone-input');
    formGroup.appendChild(label);

    const input = document.createElement('input');
    input.type = 'tel';
    input.id = 'trypbot-phone-input';
    input.className = 'trypbot-form-input';
    input.placeholder = 'Enter your phone number';
    input.required = true;
    formGroup.appendChild(input);

    const error = document.createElement('div');
    error.className = 'trypbot-form-error';
    error.textContent = 'Please enter a valid phone number';
    formGroup.appendChild(error);

    form.appendChild(formGroup);

    const continueBtn = document.createElement('button');
    continueBtn.className = 'trypbot-continue-button';
    continueBtn.textContent = 'Get Started';
    continueBtn.disabled = true;
    form.appendChild(continueBtn);

    screen.appendChild(form);

    // Store elements
    elements.phoneInput = input;
    elements.phoneError = error;
    elements.phoneContinueBtn = continueBtn;

    // Add event listeners
    input.addEventListener('input', () => {
      const phone = input.value.trim();
      if (phone.length >= 10) {
        continueBtn.disabled = false;
        input.classList.remove('error');
        error.classList.remove('visible');
      } else {
        continueBtn.disabled = true;
      }
    });

    continueBtn.addEventListener('click', async () => {
      const phone = input.value.trim();
      if (phone.length >= 10) {
        continueBtn.disabled = true;
        continueBtn.textContent = 'Creating...';
        
        try {
          await createLeadWithPhone(phone);
          showChatScreen();
          // Send welcome message
          addMessage(config.welcomeMessage, 'bot');
        } catch (error) {
          console.error('TrypBot: Error creating lead', error);
          continueBtn.disabled = false;
          continueBtn.textContent = 'Get Started';
          input.classList.add('error');
          error.classList.add('visible');
        }
      }
    });

    return screen;
  }

  /**
   * Create welcome screen element
   * @returns {HTMLElement} Welcome screen element
   */
  function createWelcomeScreen() {
    // This function is deprecated - we now create anonymous leads automatically
    // Kept for backward compatibility but not used
    const screen = document.createElement('div');
    screen.className = 'trypbot-welcome-screen';
    screen.textContent = 'Loading...';
    return screen;
  }

  /**
   * Create chat screen element
   * @returns {HTMLElement} Chat screen element
   */
  function createChatScreen() {
    const screen = document.createElement('div');
    screen.className = 'trypbot-chat-screen';

    // Messages container
    const messages = document.createElement('div');
    messages.className = 'trypbot-messages';
    screen.appendChild(messages);

    // Typing indicator
    const typingIndicator = document.createElement('div');
    typingIndicator.className = 'trypbot-typing-indicator';
    typingIndicator.setAttribute('aria-live', 'polite');
    typingIndicator.innerHTML = `
      <div class="trypbot-typing-dot"></div>
      <div class="trypbot-typing-dot"></div>
      <div class="trypbot-typing-dot"></div>
    `;
    screen.appendChild(typingIndicator);

    elements.messages = messages;
    elements.typingIndicator = typingIndicator;

    return screen;
  }

  /**
   * Create input area element
   * @returns {HTMLElement} Input area element
   */
  function createInputArea() {
    const area = document.createElement('div');
    area.className = 'trypbot-input-area';

    // Emoji button
    if (config.enableEmoji) {
      const emojiBtn = document.createElement('button');
      emojiBtn.className = 'trypbot-emoji-button';
      emojiBtn.setAttribute('aria-label', 'Insert emoji');
      emojiBtn.innerHTML = `
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10"></circle>
          <path d="M8 14s1.5 2 4 2 4-2 4-2"></path>
          <line x1="9" y1="9" x2="9.01" y2="9"></line>
          <line x1="15" y1="9" x2="15.01" y2="9"></line>
        </svg>
      `;
      emojiBtn.addEventListener('click', () => toggleEmojiPicker());
      area.appendChild(emojiBtn);
    }

    // Input wrapper
    const wrapper = document.createElement('div');
    wrapper.className = 'trypbot-input-wrapper';

    const input = document.createElement('textarea');
    input.className = 'trypbot-message-input';
    input.placeholder = 'Type your message...';
    input.rows = 1;
    input.setAttribute('aria-label', 'Message input');
    wrapper.appendChild(input);

    area.appendChild(wrapper);

    // Send button
    const sendBtn = document.createElement('button');
    sendBtn.className = 'trypbot-send-button';
    sendBtn.setAttribute('aria-label', 'Send message');
    sendBtn.disabled = true;
    sendBtn.innerHTML = `
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <line x1="22" y1="2" x2="11" y2="13"></line>
        <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
      </svg>
    `;
    area.appendChild(sendBtn);

    elements.messageInput = input;
    elements.sendBtn = sendBtn;

    // Add event listeners
    input.addEventListener('input', handleInput);
    input.addEventListener('keydown', handleKeyDown);
    sendBtn.addEventListener('click', handleSend);

    return area;
  }

  // ============================================
  // EVENT HANDLERS
  // ============================================
  
  /**
   * Handle floating button click
   */
  function handleButtonClick() {
    console.log('TrypBot: Button clicked, current isOpen:', state.isOpen, 'isAutoOpening:', state.isAutoOpening);
    if (state.isAutoOpening) {
      // Ignore clicks during auto-open
      state.isAutoOpening = false;
      return;
    }
    if (state.isOpen) {
      closeChat();
    } else {
      openChat();
    }
  }

  /**
   * Open chat window
   */
  function openChat() {
    console.log('TrypBot: openChat called, current isOpen:', state.isOpen);
    state.isOpen = true;
    state.isMinimized = false;
    elements.chatWindow.classList.add('open');
    elements.chatWindow.classList.remove('closing');
    elements.floatingButton.setAttribute('aria-expanded', 'true');
    elements.floatingButton.classList.remove('pulse');
    console.log('TrypBot: Chat window classes updated');
    
    // Prevent body scrolling on mobile when chat is open
    if (window.innerWidth <= 768) {
      document.body.style.overflow = 'hidden';
      document.body.style.position = 'fixed';
      document.body.style.width = '100%';
    }
    
    // Clear unread count when opening
    state.unreadCount = 0;
    updateUnreadBadge();

    // Auto-focus input if chat screen is visible
    if (elements.messageInput) {
      setTimeout(() => elements.messageInput.focus(), 300);
    }
  }

  /**
   * Close chat window
   */
  function closeChat() {
    console.log('TrypBot: closeChat called, isOpen:', state.isOpen);
    state.isOpen = false;
    elements.chatWindow.classList.remove('open');
    elements.chatWindow.classList.add('closing');
    elements.floatingButton.setAttribute('aria-expanded', 'false');
    elements.floatingButton.classList.add('pulse');
    
    // Restore body scrolling on mobile when chat is closed
    if (window.innerWidth <= 768) {
      document.body.style.overflow = '';
      document.body.style.position = '';
      document.body.style.width = '';
    }
    
    setTimeout(() => {
      elements.chatWindow.classList.remove('closing');
    }, 300);
  }

  /**
   * Toggle minimize state
   */
  function toggleMinimize() {
    state.isMinimized = !state.isMinimized;
    if (state.isMinimized) {
      elements.chatWindow.style.transform = 'translateY(100%)';
      elements.chatWindow.style.opacity = '0';
    } else {
      elements.chatWindow.style.transform = '';
      elements.chatWindow.style.opacity = '';
    }
  }

  /**
   * Validate form inputs
   */
  function validateForm() {
    // This function is deprecated - phone validation is now handled in createPhoneInputScreen
  }

  /**
   * Handle form submission
   * @param {Event} event - Submit event
   */
  async function handleFormSubmit(event) {
    // This function is deprecated - form submission is now handled in createPhoneInputScreen
  }

  /**
   * Handle input changes
   */
  function handleInput() {
    const value = elements.messageInput.value.trim();
    elements.sendBtn.disabled = value.length === 0;
    
    // Auto-resize textarea
    elements.messageInput.style.height = 'auto';
    elements.messageInput.style.height = Math.min(elements.messageInput.scrollHeight, 120) + 'px';
  }

  /**
   * Handle keyboard events
   * @param {KeyboardEvent} event - Keyboard event
   */
  function handleKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      if (!elements.sendBtn.disabled) {
        handleSend();
      }
    } else if (event.key === 'Escape') {
      closeChat();
    }
  }

  /**
   * Handle send button click
   */
  async function handleSend() {
    const message = elements.messageInput.value.trim();
    if (!message || !state.leadId) return;

    // Add user message to UI
    addMessage(message, 'user');
    
    // Clear input
    elements.messageInput.value = '';
    elements.messageInput.style.height = 'auto';
    elements.sendBtn.disabled = true;

    // Show typing indicator
    setTypingIndicator(true);

    try {
      // Send message via API
      const response = await sendMessage({
        lead_id: state.leadId,
        message: message
      });

      // Hide typing indicator
      setTypingIndicator(false);

      console.log('TrypBot: Full response:', response);

      // Check for human takeover
      if (response.human_takeover) {
        console.log('TrypBot: Human takeover detected, adding WhatsApp message');
        // Add takeover message with WhatsApp button
        addWhatsAppMessage(response.message, response.whatsapp_number);
        // Auto-close chat after showing WhatsApp button
        setTimeout(() => {
          closeChat();
        }, 3000);
        return;
      }

      // Add bot response with options
      if (response.message) {
        console.log('TrypBot: Bot response options:', response.options);
        addMessage(response.message, 'bot', response.options || []);
      }

      // Save conversation to storage
      state.conversation.push({ message, type: 'user', time: new Date().toISOString() });
      if (response.message) {
        state.conversation.push({ message: response.message, type: 'bot', time: new Date().toISOString() });
      }
      setToStorage(STORAGE_KEYS.CONVERSATION, state.conversation);

    } catch (error) {
      console.error('TrypBot: Error sending message', error);
      setTypingIndicator(false);
      addMessage('Sorry, there was an error sending your message. Please try again.', 'bot');
    }
  }

  /**
   * Handle click outside chat window
   * @param {Event} event - Click event
   */
  function handleOutsideClick(event) {
    if (state.isOpen && 
        !elements.chatWindow.contains(event.target) && 
        !elements.floatingButton.contains(event.target)) {
      // Don't close on outside click (as per requirements)
      // closeChat();
    }
  }

  // ============================================
  // UI FUNCTIONS
  // ============================================
  
  /**
   * Add message to chat
   * @param {string} text - Message text
   * @param {string} type - Message type ('user' or 'bot')
   * @param {Array} options - Optional array of option strings
   */
  function addMessage(text, type, options = []) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `trypbot-message ${type}`;

    const bubble = document.createElement('div');
    bubble.className = 'trypbot-message-bubble';
    
    // Add message text with formatting support
    const textElement = document.createElement('div');
    textElement.className = 'trypbot-message-text';
    textElement.innerHTML = formatMessage(text);
    bubble.appendChild(textElement);

    // Add options if provided (for bot messages)
    if (type === 'bot' && options.length > 0) {
      const optionsContainer = document.createElement('div');
      optionsContainer.className = 'trypbot-message-options';
      
      options.forEach(option => {
        const optionBtn = document.createElement('button');
        optionBtn.className = 'trypbot-option-btn';
        optionBtn.textContent = option;
        optionBtn.onclick = () => {
          // Send the selected option as a message
          elements.messageInput.value = option;
          handleSend();
        };
        optionsContainer.appendChild(optionBtn);
      });
      
      bubble.appendChild(optionsContainer);
    }

    messageDiv.appendChild(bubble);

    const time = document.createElement('div');
    time.className = 'trypbot-message-time';
    time.textContent = formatTime(new Date());
    messageDiv.appendChild(time);

    elements.messages.appendChild(messageDiv);
    scrollToBottom();
  }

  /**
   * Format message text with basic markdown support
   * @param {string} text - Raw message text
   * @returns {string} Formatted HTML
   */
  function formatMessage(text) {
    if (!text) return '';
    
    // Escape HTML to prevent XSS
    let formatted = text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
    
    // Convert line breaks to <br>
    formatted = formatted.replace(/\n\n/g, '<br><br>');
    formatted = formatted.replace(/\n/g, '<br>');
    
    // Bold text: **text** or __text__
    formatted = formatted.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    formatted = formatted.replace(/__(.*?)__/g, '<strong>$1</strong>');
    
    // Italic text: *text* or _text_
    formatted = formatted.replace(/\*(.*?)\*/g, '<em>$1</em>');
    formatted = formatted.replace(/_(.*?)_/g, '<em>$1</em>');
    
    return formatted;
  }

  /**
   * Set typing indicator visibility
   * @param {boolean} isVisible - Whether to show typing indicator
   */
  function setTypingIndicator(isVisible) {
    state.isTyping = isVisible;
    if (isVisible) {
      elements.typingIndicator.classList.add('visible');
      elements.messages.appendChild(elements.typingIndicator);
    } else {
      elements.typingIndicator.classList.remove('visible');
    }
    scrollToBottom();
  }

  /**
   * Scroll messages to bottom
   */
  function scrollToBottom() {
    setTimeout(() => {
      elements.messages.scrollTop = elements.messages.scrollHeight;
    }, 100);
  }

  /**
   * Update unread badge
   */
  function updateUnreadBadge() {
    const badge = elements.floatingButton.querySelector('.trypbot-unread-badge');
    if (!badge) return;
    
    if (state.unreadCount > 0) {
      badge.textContent = state.unreadCount > 9 ? '9+' : state.unreadCount;
      badge.classList.add('visible');
    } else {
      badge.classList.remove('visible');
    }
  }

  /**
   * Toggle emoji picker
   */
  function toggleEmojiPicker() {
    const existingPicker = document.querySelector('.trypbot-emoji-picker');
    if (existingPicker) {
      existingPicker.remove();
      return;
    }

    const picker = document.createElement('div');
    picker.className = 'trypbot-emoji-picker';
    
    const emojis = [
      '😀', '😃', '😄', '😁', '😆', '😅', '😂', '🤣',
      '😊', '😇', '🙂', '🙃', '😉', '😌', '😍', '🥰',
      '😘', '😗', '😙', '😚', '😋', '😛', '😜', '🤪',
      '😝', '🤑', '🤗', '🤭', '🤫', '🤔', '🤐', '🤨',
      '😐', '😑', '😶', '😏', '😒', '🙄', '😬', '🤥',
      '😌', '😔', '😪', '🤤', '😴', '😷', '🤒', '🤕',
      '👍', '👎', '👌', '✌️', '🤞', '🤟', '🤘', '🤙',
      '👏', '🙌', '👐', '🤲', '🤝', '🙏', '✍️', '💪',
      '❤️', '🧡', '💛', '💚', '💙', '💜', '🖤', '🤍',
      '💯', '💢', '💥', '💫', '💦', '💨', '🕳️', '💣',
      '🎉', '🎊', '🎈', '🎁', '🏆', '🥇', '🥈', '🥉'
    ];

    emojis.forEach(emoji => {
      const emojiBtn = document.createElement('button');
      emojiBtn.className = 'trypbot-emoji-item';
      emojiBtn.textContent = emoji;
      emojiBtn.addEventListener('click', () => {
        const input = elements.messageInput;
        const start = input.selectionStart;
        const end = input.selectionEnd;
        const text = input.value;
        input.value = text.substring(0, start) + emoji + text.substring(end);
        input.focus();
        input.selectionStart = input.selectionEnd = start + emoji.length;
        picker.remove();
      });
      picker.appendChild(emojiBtn);
    });

    const inputArea = elements.inputArea;
    inputArea.appendChild(picker);

    // Close picker when clicking outside
    setTimeout(() => {
      document.addEventListener('click', closeEmojiPickerOutside);
    }, 0);
  }

  /**
   * Close emoji picker when clicking outside
   */
  function closeEmojiPickerOutside(event) {
    const picker = document.querySelector('.trypbot-emoji-picker');
    const emojiBtn = elements.inputArea.querySelector('.trypbot-emoji-button');
    
    if (picker && !picker.contains(event.target) && !emojiBtn.contains(event.target)) {
      picker.remove();
      document.removeEventListener('click', closeEmojiPickerOutside);
    }
  }

  /**
   * Add WhatsApp message with redirect button
   * @param {string} message - Message text
   * @param {string} whatsappNumber - WhatsApp phone number
   */
  function addWhatsAppMessage(message, whatsappNumber) {
    console.log('TrypBot: Adding WhatsApp message with number:', whatsappNumber);
    const messageDiv = document.createElement('div');
    messageDiv.className = 'trypbot-message bot';

    const bubble = document.createElement('div');
    bubble.className = 'trypbot-message-bubble';
    
    const textElement = document.createElement('div');
    textElement.className = 'trypbot-message-text';
    textElement.innerHTML = formatMessage(message);
    bubble.appendChild(textElement);

    // WhatsApp button
    const whatsappBtn = document.createElement('a');
    whatsappBtn.className = 'trypbot-whatsapp-btn';
    whatsappBtn.href = `https://wa.me/${whatsappNumber}`;
    whatsappBtn.target = '_blank';
    whatsappBtn.rel = 'noopener noreferrer';
    whatsappBtn.innerHTML = `
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" width="20" height="20">
        <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/>
      </svg>
      Chat on WhatsApp
    `;
    bubble.appendChild(whatsappBtn);

    messageDiv.appendChild(bubble);

    const time = document.createElement('div');
    time.className = 'trypbot-message-time';
    time.textContent = formatTime(new Date());
    messageDiv.appendChild(time);

    elements.messages.appendChild(messageDiv);
    scrollToBottom();
  }

  /**
   * Disable input area
   */
  function disableInput() {
    if (elements.messageInput) {
      elements.messageInput.disabled = true;
      elements.messageInput.placeholder = 'Chat transferred to WhatsApp';
    }
    if (elements.sendButton) {
      elements.sendButton.disabled = true;
    }
    if (elements.inputArea) {
      const emojiBtn = elements.inputArea.querySelector('.trypbot-emoji-button');
      if (emojiBtn) {
        emojiBtn.disabled = true;
      }
    }
  }

  /**
   * Show welcome screen
   */
  function showWelcomeScreen() {
    elements.content.innerHTML = '';
    const welcomeScreen = createWelcomeScreen();
    elements.content.appendChild(welcomeScreen);
    elements.inputArea.style.display = 'none';
  }

  /**
   * Show phone input screen
   */
  function showPhoneInputScreen() {
    elements.content.innerHTML = '';
    const phoneScreen = createPhoneInputScreen();
    elements.content.appendChild(phoneScreen);
    elements.inputArea.style.display = 'none';
  }

  /**
   * Show chat screen
   */
  function showChatScreen() {
    elements.content.innerHTML = '';
    const chatScreen = createChatScreen();
    elements.content.appendChild(chatScreen);
    elements.inputArea.style.display = 'flex';

    // Load previous conversation
    const savedConversation = getFromStorage(STORAGE_KEYS.CONVERSATION);
    if (savedConversation && savedConversation.length > 0) {
      savedConversation.forEach(msg => {
        addMessage(msg.message, msg.type);
      });
    } else {
      // Send welcome message for new users with destination options
      setTimeout(() => {
        const destinations = ['Rameshwaram', 'Varanasi', 'Ayodhya', 'Nashik', 'Puri', 'Ujjain', 'Coorg', 'Dwarka', 'Gokarna', 'Other (Please Specify)'];
        addMessage(config.welcomeMessage, 'bot', destinations);
      }, 500);
    }
  }

  /**
   * Apply theme
   * @param {string} theme - Theme name ('light' or 'dark')
   */
  function applyTheme(theme) {
    state.theme = theme;
    document.documentElement.setAttribute('data-trypbot-theme', theme);
    setToStorage(STORAGE_KEYS.THEME, theme);
  }

  /**
   * Toggle theme
   */
  function toggleTheme() {
    const newTheme = state.theme === 'light' ? 'dark' : 'light';
    applyTheme(newTheme);
  }

  // ============================================
  // INITIALIZATION
  // ============================================
  
  /**
   * Load CSS
   */
  function loadCSS() {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = `${config.staticBase}/widget.css`;
    link.crossOrigin = 'anonymous';
    document.head.appendChild(link);
  }

  /**
   * Initialize widget
   */
  async function init() {
    // Load CSS
    loadCSS();

    // Load saved state
    state.leadId = getFromStorage(STORAGE_KEYS.LEAD_ID);
    state.userName = getFromStorage(STORAGE_KEYS.USER_NAME);
    state.userPhone = getFromStorage(STORAGE_KEYS.USER_PHONE);
    state.conversation = getFromStorage(STORAGE_KEYS.CONVERSATION) || [];
    state.theme = getFromStorage(STORAGE_KEYS.THEME) || config.theme;

    // Apply theme
    applyTheme(state.theme);

    // Create DOM elements
    elements.floatingButton = createFloatingButton();
    elements.chatWindow = createChatWindow();
    elements.content = elements.chatWindow.querySelector('.trypbot-content');
    elements.inputArea = elements.chatWindow.querySelector('.trypbot-input-area');

    // Add to DOM
    document.body.appendChild(elements.floatingButton);
    document.body.appendChild(elements.chatWindow);

    // Add event listeners
    elements.floatingButton.addEventListener('click', handleButtonClick);
    document.addEventListener('click', handleOutsideClick);
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && state.isOpen) {
        closeChat();
      }
    });

    // Show appropriate screen
    if (state.leadId) {
      showChatScreen();
      // Connect WebSocket
      connectSocket();
    } else {
      // Show phone input screen for new users
      showPhoneInputScreen();
    }

    // Widget is always open by default, so call openChat to ensure it's visible
    openChat();

    console.log('TrypBot Widget initialized successfully');
  }

  // ============================================
  // PUBLIC API
  // ============================================
  
  // Expose public methods
  window.TrypBot = {
    open: openChat,
    close: closeChat,
    toggle: () => state.isOpen ? closeChat() : openChat(),
    setTheme: applyTheme,
    getTheme: () => state.theme,
    clearData: clearStorage,
    getVersion: () => '1.0.0'
  };

  // Initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => init());
  } else {
    init();
  }

})();
