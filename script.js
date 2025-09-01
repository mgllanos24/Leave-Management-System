// Backend Database API Implementation to replace LocalDatabase
class BackendDatabase {
    constructor() {
        /* @tweakable API base URL for backend database */
        this.baseUrl = '/api';
        
        /* @tweakable request timeout in milliseconds - reduced for better UX */
        this.requestTimeout = 8000;
        
        /* @tweakable whether to enable database API debugging */
        this.debugMode = true;
        
        /* @tweakable whether to log JavaScript loading and initialization errors */
        this.enableScriptDebugging = true;
        
        /* @tweakable maximum retry attempts for failed requests */
        this.maxRetries = 3;
        
        /* @tweakable delay between retry attempts in milliseconds */
        this.retryDelay = 1000;
        
        this.collections = {};
        this.subscribers = {};
    }

    collection(name) {
        if (!this.collections[name]) {
            this.collections[name] = new BackendCollection(name, this);
        }
        return this.collections[name];
    }
}

class BackendCollection {
    constructor(name, database) {
        this.name = name;
        this.database = database;
        this.subscribers = [];
        this.filters = {};
        this.cachedData = [];
        this.lastFetchTime = 0;
        
        /* @tweakable cache duration in milliseconds */
        this.cacheTimeout = 5000;
    }

    async makeRequest(method, path = '', data = null) {
        const url = `${this.database.baseUrl}/${this.name}${path}`;
        
        for (let attempt = 1; attempt <= this.database.maxRetries; attempt++) {
            try {
                const controller = new AbortController();
                const timeoutId = setTimeout(() => controller.abort(), this.database.requestTimeout);
                
                const options = {
                    method: method,
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    signal: controller.signal
                };
                
                if (data) {
                    options.body = JSON.stringify(data);
                }
                
                if (this.database.debugMode) {
                    console.log(`🔄 ${method} ${url}`, data ? data : '');
                }
                
                const response = await fetch(url, options);
                clearTimeout(timeoutId);
                
                if (!response.ok) {
                    const errorText = await response.text().catch(() => 'Unknown error');
                    throw new Error(`HTTP ${response.status}: ${errorText}`);
                }
                
                const result = await response.json();
                
                if (this.database.debugMode) {
                    console.log(`✅ ${method} ${url} success`, result);
                }
                
                return result;
                
            } catch (error) {
                if (attempt === this.database.maxRetries) {
                    console.error(`❌ ${method} ${url} failed after ${attempt} attempts:`, error);
                    throw error;
                } else {
                    console.warn(`⚠️ ${method} ${url} attempt ${attempt} failed, retrying...`, error.message);
                    await new Promise(resolve => setTimeout(resolve, this.database.retryDelay));
                }
            }
        }
    }

    async getList() {
        try {
            // Check cache validity
            const now = Date.now();
            if (this.cachedData.length > 0 && now - this.lastFetchTime < this.cacheTimeout) {
                return this.applyFilters(this.cachedData);
            }
            
            const data = await this.makeRequest('GET');
            this.cachedData = data || [];
            this.lastFetchTime = now;
            
            return this.applyFilters(this.cachedData);
        } catch (error) {
            console.error(`Error fetching ${this.name}:`, error);
            return this.applyFilters(this.cachedData); // Return cached data on error
        }
    }

    applyFilters(data) {
        if (Object.keys(this.filters).length === 0) {
            return data;
        }
        
        return data.filter(item => {
            return Object.entries(this.filters).every(([key, value]) => {
                return item[key] === value;
            });
        });
    }

    async create(data) {
        try {
            const result = await this.makeRequest('POST', '', data);
            
            // Invalidate cache
            this.lastFetchTime = 0;
            
            // Notify subscribers
            setTimeout(() => this.notifySubscribers(), 100);
            
            return result;
        } catch (error) {
            console.error(`Error creating ${this.name}:`, error);
            throw error;
        }
    }

    async update(id, data) {
        try {
            const result = await this.makeRequest('PUT', `/${id}`, data);
            
            // Invalidate cache
            this.lastFetchTime = 0;
            
            // Notify subscribers
            setTimeout(() => this.notifySubscribers(), 100);
            
            return result;
        } catch (error) {
            console.error(`Error updating ${this.name}:`, error);
            throw error;
        }
    }

    async delete(id) {
        try {
            const result = await this.makeRequest('DELETE', `/${id}`);
            
            // Invalidate cache
            this.lastFetchTime = 0;
            
            // Notify subscribers
            setTimeout(() => this.notifySubscribers(), 100);
            
            return result;
        } catch (error) {
            console.error(`Error deleting ${this.name}:`, error);
            throw error;
        }
    }

    filter(filterObj) {
        const filteredCollection = new BackendCollection(this.name, this.database);
        filteredCollection.filters = { ...this.filters, ...filterObj };
        filteredCollection.cachedData = this.cachedData;
        filteredCollection.lastFetchTime = this.lastFetchTime;
        return filteredCollection;
    }

    subscribe(callback) {
        this.subscribers.push(callback);
        
        // Call immediately with current data
        this.getList().then(data => {
            try {
                callback(data);
            } catch (error) {
                console.error('Error in subscriber callback:', error);
            }
        });
        
        // Return unsubscribe function
        return () => {
            const index = this.subscribers.indexOf(callback);
            if (index > -1) {
                this.subscribers.splice(index, 1);
            }
        };
    }

    async notifySubscribers() {
        try {
            const data = await this.getList();
            this.subscribers.forEach(callback => {
                try {
                    callback(data);
                } catch (error) {
                    console.error('Error in subscriber callback:', error);
                }
            });
        } catch (error) {
            console.error('Error notifying subscribers:', error);
        }
    }
}

// Global variables and initialization
/* @tweakable prefer backend API over local storage */
const USE_BACKEND_DATABASE = true;
if (USE_BACKEND_DATABASE) {
    if (!window.room || !(window.room instanceof BackendDatabase)) {
        window.room = new BackendDatabase();
        console.log('✅ room initialized with BackendDatabase');
    }
}
const room = window.room;

// Authentication globals
let currentUserType = null;
let currentUser = null;

/* @tweakable localStorage keys for authentication persistence */
const AUTH_TYPE_KEY = 'elms_auth_type';
const AUTH_USER_KEY = 'elms_auth_user';

/* @tweakable authentication configuration */
const PERSIST_AUTH_STATE = true;
const AUTO_RESTORE_AUTH = true;
const CLEAR_AUTH_ON_LOGOUT_ONLY = true;
const AUTH_SESSION_TIMEOUT = 0;

/* @tweakable whether to enable detailed employee form submission debugging */
const enableEmployeeFormDebugging = true;

/* @tweakable maximum retry attempts for employee form submission */
const maxEmployeeFormRetries = 3;

/* @tweakable delay between employee form submission retries in milliseconds */
const employeeFormRetryDelay = 1000;

/* @tweakable whether to show visual feedback during employee creation */
const showEmployeeCreationFeedback = true;

/* @tweakable timeout for employee form submission in milliseconds - reduced for better responsiveness */
const employeeFormTimeout = 5000;

// @tweakable bootstrap employee data (balances, history) on successful login
const ENABLE_EMPLOYEE_BOOTSTRAP_ON_LOGIN = true;

// Minimal LeaveBalanceAPI used across UI
window.LeaveBalanceAPI = {
    /* @tweakable show detailed admin balance in tables */
    showDetailedAdminBalance: true,
    /* @tweakable show balance history column in admin view */
    showBalanceHistoryCount: false,
    /* @tweakable low-balance threshold in days for color cue */
    lowBalanceThreshold: 3,
    /* @tweakable employee balance cache for performance */
    employeeBalanceCache: new Map(),
    /* @tweakable cache timeout for employee balances in milliseconds */
    employeeBalanceCacheTimeout: 30000,

    /* @tweakable clear balance cache for specific employee to force fresh data */
    clearEmployeeBalanceCache(employeeId = null) {
        if (employeeId) {
            this.employeeBalanceCache.delete(employeeId);
        } else {
            this.employeeBalanceCache.clear();
        }
    },

    async getEmployeeBalances(/* @tweakable employeeId to filter (null = all) */ employeeId = null) {
        /* @tweakable whether to use caching for employee balance requests */
        const useCaching = true;
        
        // Check cache if enabled and querying specific employee
        if (useCaching && employeeId) {
            const cacheKey = employeeId;
            const cached = this.employeeBalanceCache.get(cacheKey);
            
            if (cached && Date.now() - cached.timestamp < this.employeeBalanceCacheTimeout) {
                return cached.data.filter(b => b.employee_id === employeeId);
            }
        }
        
        const all = await room.collection('leave_balance').getList();
        
        // Update cache if enabled and we have data
        if (useCaching && employeeId && all.length > 0) {
            this.employeeBalanceCache.set(employeeId, {
                data: all,
                timestamp: Date.now()
            });
        }
        
        return employeeId ? all.filter(b => b.employee_id === employeeId) : all;
    },

    getBalanceColor(balance, kind) {
        if (!balance) return '#64748b';
        if (balance.remaining_days <= 0) return '#dc2626';
        if (balance.remaining_days <= this.lowBalanceThreshold) return '#ea580c';
        return kind === 'sick' ? '#065f46' : '#2563eb';
    },

    async setRemainingDays(/* @tweakable employee id */ employeeId, /* @tweakable balance type */ balanceType, /* @tweakable new remaining days */ remaining) {
        const balances = await this.getEmployeeBalances(employeeId);
        const bal = balances.find(b => b.balance_type === balanceType);
        if (!bal) throw new Error(`Balance not found for ${balanceType}`);
        return await room.collection('leave_balance').update(bal.id, { remaining_days: parseFloat(remaining) });
    }
};

// Handle login and app initialization
document.addEventListener('DOMContentLoaded', function() {
    /* @tweakable whether to show debug messages during login flow initialization */
    const debugLoginFlow = true;
    
    /* @tweakable whether to validate app container visibility on page load */
    const validateInitialVisibility = true;
    
    /* @tweakable delay in milliseconds before setting up login handlers */
    const loginHandlerDelay = 500;
    
    /* @tweakable maximum retry attempts for finding login elements */
    const maxLoginElementRetries = 5;
    
    /* @tweakable delay between retries when finding login elements */
    const loginElementRetryDelay = 200;
    
    /* @tweakable whether to enable extensive button debugging */
    const enableButtonDebugging = false;
    
    /* @tweakable whether to add visual debugging indicators to buttons */
    const addVisualDebugging = false;
    
    /* @tweakable whether to log DOM state during initialization */
    const logDOMState = true;
    
    if (debugLoginFlow) {
        console.log('🚀 Initializing Employee Leave Management System...');
        console.log('📊 Page Load Debug Info:');
        console.log('- Current URL:', window.location.href);
        console.log('- DOM Ready State:', document.readyState);
        console.log('- Script Loading Time:', new Date().toISOString());
    }
    
    // Try to restore authentication state first
    if (AUTO_RESTORE_AUTH && PERSIST_AUTH_STATE) {
        try {
            restoreAuthenticationState();
            if (currentUserType && currentUser) {
                if (debugLoginFlow) {
                    console.log('✅ Authentication state restored from localStorage');
                    console.log('- User Type:', currentUserType);
                    console.log('- User:', currentUser.first_name || currentUser.username);
                }
                
                // Hide entry/login containers and show main app
                document.getElementById('entryContainer').style.display = 'none';
                document.getElementById('employeeLoginContainer').style.display = 'none';
                document.getElementById('adminLoginContainer').style.display = 'none';
                document.getElementById('appContainer').style.display = 'block';

                // Ensure employee info fields reflect restored user
                updateEmployeeInfo();

                // Configure and initialize app
                configureTabsForUser();
                displayWelcome();
                setTimeout(() => {
                    initializeApp();
                }, 100);
                
                if (debugLoginFlow) {
                    console.log('🎉 App restored with saved authentication');
                }
                return; // Skip normal entry point flow
            }
        } catch (error) {
            console.error('Error restoring authentication state:', error);
            clearPersistedAuthState();
        }
    }
    
    // Enhanced DOM state logging
    if (logDOMState) {
        console.log('📋 DOM State Check:');
        console.log('- Entry Container:', document.getElementById('entryContainer'));
        console.log('- Employee Entry Button:', document.getElementById('employeeEntryBtn'));
        console.log('- Admin Entry Button:', document.getElementById('adminEntryBtn'));
        console.log('- Employee Login Container:', document.getElementById('employeeLoginContainer'));
        console.log('- Admin Login Container:', document.getElementById('adminLoginContainer'));
        console.log('- App Container:', document.getElementById('appContainer'));
    }
    
    // Ensure proper initial state - only entry selection should be visible
    if (validateInitialVisibility) {
        document.getElementById('appContainer').style.display = 'none';
        document.getElementById('employeeLoginContainer').style.display = 'none';
        document.getElementById('adminLoginContainer').style.display = 'none';
    }

    // Attach button click handlers
    const employeeEntryBtn = document.getElementById('employeeEntryBtn');
    if (employeeEntryBtn) {
        employeeEntryBtn.addEventListener('click', showEmployeeLogin);
    }

    const adminEntryBtn = document.getElementById('adminEntryBtn');
    if (adminEntryBtn) {
        adminEntryBtn.addEventListener('click', showAdminLogin);
    }

    const tabLeaveRequest = document.getElementById('tabLeaveRequest');
    if (tabLeaveRequest) {
        tabLeaveRequest.addEventListener('click', () => switchTab('leave-request'));
    }
    const tabCheckHistory = document.getElementById('tabCheckHistory');
    if (tabCheckHistory) {
        tabCheckHistory.addEventListener('click', () => switchTab('check-history'));
    }
    const tabEmployeeManagement = document.getElementById('tabEmployeeManagement');
    if (tabEmployeeManagement) {
        tabEmployeeManagement.addEventListener('click', () => switchTab('employee-management'));
    }
    const tabApplicationStatus = document.getElementById('tabApplicationStatus');
    if (tabApplicationStatus) {
        tabApplicationStatus.addEventListener('click', () => switchTab('application-status'));
    }
    const tabHolidayDates = document.getElementById('tabHolidayDates');
    if (tabHolidayDates) {
        tabHolidayDates.addEventListener('click', () => switchTab('holiday-dates'));
    }

    const deleteAllBtn = document.getElementById('deleteAllBtn');
    if (deleteAllBtn) {
        deleteAllBtn.addEventListener('click', deleteAllEmployees);
    }

    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.addEventListener('click', () => filterApplications(btn.dataset.status));
    });

    const exportBackupBtn = document.getElementById('exportBackupBtn');
    if (exportBackupBtn) {
        exportBackupBtn.addEventListener('click', exportDatabaseBackup);
    }

    const importBackupBtn = document.getElementById('importBackupBtn');
    if (importBackupBtn) {
        importBackupBtn.addEventListener('click', importDatabaseBackup);
    }

    const errorModalClose = document.getElementById('errorModalClose');
    if (errorModalClose) {
        errorModalClose.addEventListener('click', closeErrorModal);
    }

    const errorModalOk = document.getElementById('errorModalOk');
    if (errorModalOk) {
        errorModalOk.addEventListener('click', closeErrorModal);
    }

    const editModalClose = document.getElementById('editModalClose');
    if (editModalClose) {
        editModalClose.addEventListener('click', closeEditModal);
    }

    const editModalCancel = document.getElementById('editModalCancel');
    if (editModalCancel) {
        editModalCancel.addEventListener('click', closeEditModal);
    }
    
    // Add visual debugging indicators to buttons if enabled
    if (addVisualDebugging && enableButtonDebugging) {
        setTimeout(() => {
            const employeeBtn = document.getElementById('employeeEntryBtn');
            const adminBtn = document.getElementById('adminEntryBtn');
            
            if (employeeBtn) {
                employeeBtn.style.border = '2px dashed red';
                employeeBtn.title = 'DEBUG: Employee button found and marked';
                console.log('🔍 Visual debug marker added to employee button');
            } else {
                console.error('🚨 Employee button not found for visual debugging');
            }
            
            if (adminBtn) {
                adminBtn.style.border = '2px dashed red';
                adminBtn.title = 'DEBUG: Admin button found and marked';
                console.log('🔍 Visual debug marker added to admin button');
            } else {
                console.error('🚨 Admin button not found for visual debugging');
            }
        }, 100);
    }
    
    // Ensure button handlers work as backup
    if (enableButtonDebugging) {
        setTimeout(() => {
            const employeeBtn = document.getElementById('employeeEntryBtn');
            const adminBtn = document.getElementById('adminEntryBtn');

            console.log('🔧 Setting up backup button handlers...');

            if (employeeBtn) {
                employeeBtn.addEventListener('click', function(e) {
                    e.preventDefault();
                    console.log('🔄 Backup employee handler triggered');
                    showEmployeeLogin();
                });
                console.log('✅ Employee button handler confirmed');
            } else {
                console.error('❌ Employee button not found!');
            }

            if (adminBtn) {
                adminBtn.addEventListener('click', function(e) {
                    e.preventDefault();
                    console.log('🔄 Backup admin handler triggered');
                    showAdminLogin();
                });
                console.log('✅ Admin button handler confirmed');
            } else {
                console.error('❌ Admin button not found!');
            }
        }, 200);
    }
    
    // **FIX: Attach critical form handlers immediately to prevent race condition**
    setupCriticalFormHandlers();
    
    // Initialize local database connection (but don't show the app yet)
    initializeLocalDatabase();
    
    // Check URL parameters for direct login type
    const urlParams = new URLSearchParams(window.location.search);
    const loginType = urlParams.get('type');
    
    if (loginType === 'employee') {
        showEmployeeLogin();
    } else if (loginType === 'admin') {
        showAdminLogin();
    } else {
        // Show entry point selection
        showEntrySelection();
    }
    
    // Setup login handlers with enhanced retry logic
    const setupHandlersWithRetry = async (retryCount = 0) => {
        try {
            await setupLoginHandlers();
            if (debugLoginFlow) {
                console.log('✅ Login handlers setup completed successfully');
            }
        } catch (error) {
            console.error('❌ Error setting up login handlers:', error);
            if (retryCount < maxLoginElementRetries) {
                console.log(`🔄 Retrying login handler setup (attempt ${retryCount + 1})...`);
                setTimeout(() => setupHandlersWithRetry(retryCount + 1), loginElementRetryDelay);
            } else {
                console.error('🚨 Failed to setup login handlers after maximum retries');
                // Try direct button attachment as fallback
                setupLoginButtonsFallback();
            }
        }
    };
    
    setTimeout(() => {
        setupHandlersWithRetry();
    }, loginHandlerDelay);
    
    if (debugLoginFlow) {
        console.log('✅ Login flow initialization completed');
    }
});

// **NEW: Set up critical form handlers immediately to prevent race condition**
function setupCriticalFormHandlers() {
    /* @tweakable whether to enable immediate form handler setup debugging */
    const debugImmediateSetup = true;
    
    if (debugImmediateSetup) {
        console.log('🚀 Setting up critical form handlers immediately...');
    }
    
    // Set up employee form handler immediately
    const employeeForm = document.getElementById('employeeForm');
    if (employeeForm) {
        employeeForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            e.stopPropagation();
            
            if (debugImmediateSetup) {
                console.log('✅ Employee form submitted via immediate handler');
            }
            
            await handleEmployeeFormSubmit();
        });
        
        if (debugImmediateSetup) {
            console.log('✅ Employee form submit handler attached immediately');
        }
    }
    
    // Set up vacation form handler immediately  
    const vacationForm = document.getElementById('vacationForm');
    if (vacationForm) {
        vacationForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            e.stopPropagation();
            
            if (debugImmediateSetup) {
                console.log('✅ Vacation form submitted via immediate handler');
            }
            
            await submitLeaveApplication(e);
        });

        vacationForm.addEventListener('reset', function() {
            updateEmployeeInfo();
        });

        if (debugImmediateSetup) {
            console.log('✅ Vacation form submit handler attached immediately');
        }
    }
    
    if (debugImmediateSetup) {
        console.log('🎉 Critical form handlers setup completed');
    }
}

function setupLoginButtonsFallback() {
    /* @tweakable whether to enable fallback button setup debugging */
    const debugFallback = true;
    
    if (debugFallback) {
        console.log('🔧 Setting up fallback login button handlers...');
    }
    
    const employeeBtn = document.getElementById('employeeEntryBtn');
    const adminBtn = document.getElementById('adminEntryBtn');

    if (employeeBtn) {
        employeeBtn.addEventListener('click', function(e) {
            e.preventDefault();
            showEmployeeLogin();
        });
    }

    if (adminBtn) {
        adminBtn.addEventListener('click', function(e) {
            e.preventDefault();
            showAdminLogin();
        });
    }
}

function initializeLocalDatabase() {
    /* @tweakable database initialization timeout in milliseconds */
    const dbInitTimeout = 3000;
    
    console.log('📊 Initializing local database connection...');
    
    if (window.room) {
        console.log('✅ Database connection ready');
    } else {
        console.warn('⚠️ Database connection not available yet');
    }
}

function restoreAuthenticationState() {
    /* @tweakable authentication state restoration debugging */
    const debugAuthRestore = true;
    
    if (!PERSIST_AUTH_STATE) return;
    
    try {
        const savedType = localStorage.getItem(AUTH_TYPE_KEY);
        const savedUser = localStorage.getItem(AUTH_USER_KEY);
        
        if (savedType && savedUser) {
            currentUserType = savedType;
            currentUser = JSON.parse(savedUser);
            
            if (debugAuthRestore) {
                console.log('✅ Authentication state restored:', { type: currentUserType, user: currentUser });
            }
        }
    } catch (error) {
        console.error('Error restoring auth state:', error);
        clearPersistedAuthState();
    }
}

function clearPersistedAuthState() {
    /* @tweakable whether to clear all auth-related localStorage items */
    const clearAllAuthData = true;
    
    if (clearAllAuthData) {
        localStorage.removeItem(AUTH_TYPE_KEY);
        localStorage.removeItem(AUTH_USER_KEY);
    }
}

// Show functions
function showEntrySelection() {
    document.getElementById('entryContainer').style.display = 'block';
    document.getElementById('employeeLoginContainer').style.display = 'none';
    document.getElementById('adminLoginContainer').style.display = 'none';
    document.getElementById('appContainer').style.display = 'none';
}

function showEmployeeLogin() {
    /* @tweakable whether to log navigation to employee login */
    const logNavigation = true;
    
    if (logNavigation) {
        console.log('🔄 Navigating to employee login');
    }
    
    document.getElementById('entryContainer').style.display = 'none';
    document.getElementById('employeeLoginContainer').style.display = 'block';
    document.getElementById('adminLoginContainer').style.display = 'none';
    document.getElementById('appContainer').style.display = 'none';
}

function showAdminLogin() {
    /* @tweakable whether to log navigation to admin login */
    const logNavigation = true;
    
    if (logNavigation) {
        console.log('🔄 Navigating to admin login');
    }
    
    document.getElementById('entryContainer').style.display = 'none';
    document.getElementById('employeeLoginContainer').style.display = 'none';
    document.getElementById('adminLoginContainer').style.display = 'block';
    document.getElementById('appContainer').style.display = 'none';
}

async function setupLoginHandlers() {
    /* @tweakable login handler setup configuration */
    const enableDetailedLogging = true;
    const validateFormElements = true;
    
    if (enableDetailedLogging) {
        console.log('🔧 Setting up login form handlers...');
    }
    
    // Employee login form
    const employeeForm = document.getElementById('loginEmployeeForm');
    if (employeeForm) {
        employeeForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            const email = document.getElementById('loginEmployeeEmail').value.trim();
            
            if (email) {
                await loginEmployee(email);
            }
        });
        
        if (enableDetailedLogging) {
            console.log('✅ Employee login form handler attached');
        }
    }
    
    // Admin login form
    const adminForm = document.getElementById('loginAdminForm');
    if (adminForm) {
        adminForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            const username = document.getElementById('loginAdminUsername').value.trim();
            const password = document.getElementById('loginAdminPassword').value.trim();
            
            if (username && password) {
                await loginAdmin(username, password);
            }
        });
        
        if (enableDetailedLogging) {
            console.log('✅ Admin login form handler attached');
        }
    }
    
    // Back button handlers
    const backFromEmployee = document.getElementById('backToEntryFromEmployee');
    const backFromAdmin = document.getElementById('backToEntryFromAdmin');
    
    if (backFromEmployee) {
        backFromEmployee.addEventListener('click', showEntrySelection);
    }
    
    if (backFromAdmin) {
        backFromAdmin.addEventListener('click', showEntrySelection);
    }
    
    // Logout handler
    const logoutBtn = document.getElementById('logoutBtn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', logout);
    }
}

function generatePreviewApplicationId() {
    const datePart = new Date().toISOString().slice(0, 10).replace(/-/g, '');
    const randomPart = Math.random().toString(36).substring(2, 10).toUpperCase();
    return `APP-${datePart}-${randomPart}`;
}

async function updateEmployeeInfo() {
    const nameEl = document.getElementById('employeeDisplayName');
    if (!nameEl) {
        console.warn('employeeDisplayName element not found');
    } else if (currentUser) {
        nameEl.textContent = `${currentUser.first_name} ${currentUser.surname}`;
    }

    const idPreviewEl = document.getElementById('applicationIdPreview');
    if (!idPreviewEl) {
        console.warn('applicationIdPreview element not found');
    } else {
        let previewId = generatePreviewApplicationId();
        try {
            const resp = await fetch('/api/next_application_id');
            if (resp.ok) {
                const data = await resp.json();
                previewId = data.application_id || previewId;
            }
        } catch (err) {
            // Use generated previewId on error or if endpoint not available
        }
        idPreviewEl.textContent = previewId;
    }
}

async function loginEmployee(email) {
    /* @tweakable employee login timeout in milliseconds */
    const loginTimeout = 5000;
    
    try {
        showLoading();
        
        const response = await fetch('/api/bootstrap_employee', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email: email })
        });
        
        if (!response.ok) {
            throw new Error(`Login failed: ${response.status}`);
        }
        
        const data = await response.json();

        currentUserType = 'employee';
        currentUser = data.employee;
        await updateEmployeeInfo();

        if (PERSIST_AUTH_STATE) {
            localStorage.setItem(AUTH_TYPE_KEY, currentUserType);
            localStorage.setItem(AUTH_USER_KEY, JSON.stringify(currentUser));
        }
        
        hideLoading();
        showMainApp();
        
    } catch (error) {
        hideLoading();
        alert(`Login failed: ${error.message}`);
    }
}

async function loginAdmin(username, password) {
    /* @tweakable admin login credentials */
    const validAdminUsername = 'admin';
    const validAdminPassword = 'admin123';
    
    try {
        showLoading();
        
        if (username === validAdminUsername && password === validAdminPassword) {
            currentUserType = 'admin';
            currentUser = { username: username, first_name: 'Administrator', email: 'admin@company.com' };
            
            if (PERSIST_AUTH_STATE) {
                localStorage.setItem(AUTH_TYPE_KEY, currentUserType);
                localStorage.setItem(AUTH_USER_KEY, JSON.stringify(currentUser));
            }
            
            hideLoading();
            showMainApp();
        } else {
            throw new Error('Invalid credentials');
        }
        
    } catch (error) {
        hideLoading();
        alert(`Login failed: ${error.message}`);
    }
}

function showMainApp() {
    document.getElementById('entryContainer').style.display = 'none';
    document.getElementById('employeeLoginContainer').style.display = 'none';
    document.getElementById('adminLoginContainer').style.display = 'none';
    document.getElementById('appContainer').style.display = 'block';

    // Ensure user-specific fields are updated whenever the main app is shown
    updateEmployeeInfo();

    configureTabsForUser();
    displayWelcome();
    initializeApp();
}

function configureTabsForUser() {
    const isAdmin = currentUserType === 'admin';

    document.getElementById('tabEmployeeManagement').style.display = isAdmin ? 'block' : 'none';
    document.getElementById('tabApplicationStatus').style.display = isAdmin ? 'block' : 'none';
    document.getElementById('tabHolidayDates').style.display = isAdmin ? 'block' : 'none';
    document.getElementById('adminSection').style.display = isAdmin ? 'block' : 'none';

    // Toggle visibility for employee-specific tabs based on user role
    document.getElementById('tabLeaveRequest').style.display = isAdmin ? 'none' : 'block';
    document.getElementById('tabCheckHistory').style.display = isAdmin ? 'none' : 'block';

    // Also hide the corresponding tab content sections to prevent access
    document.getElementById('leave-request').style.display = isAdmin ? 'none' : '';
    document.getElementById('check-history').style.display = isAdmin ? 'none' : '';
}

function displayWelcome() {
    const welcomeContainer = document.getElementById('welcomeContainer');
    const welcomeName = document.getElementById('welcomeName');
    
    if (currentUser) {
        const displayName = currentUser.first_name ? 
            `Welcome, ${currentUser.first_name}!` : 
            `Welcome, ${currentUser.username}!`;
        
        welcomeName.textContent = displayName;
        welcomeContainer.style.display = 'flex';
    }
}

function logout() {
    currentUserType = null;
    currentUser = null;
    
    if (PERSIST_AUTH_STATE) {
        clearPersistedAuthState();
    }
    
    showEntrySelection();
}

function showLoading() {
    const overlay = document.getElementById('loadingOverlay');
    if (overlay) {
        overlay.classList.add('show');
    }
}

function hideLoading() {
    const overlay = document.getElementById('loadingOverlay');
    if (overlay) {
        overlay.classList.remove('show');
    }
}

// Initialize the main application
async function initializeApp() {
    /* @tweakable app initialization configuration */
    const enableInitDebug = true;
    const initTimeout = 10000;
    
    try {
        if (enableInitDebug) {
            console.log('🚀 Initializing main application...');
        }
        
        // Load initial data
        await loadEmployeeList();
        await loadLeaveApplications();
        await loadHolidays();
        
        // Set up form handlers and other functionality
        setupEmployeeManagement();
        setupLeaveApplication();
        setupDateCalculation();
        setupLeaveTypeHandling();
        
        if (enableInitDebug) {
            console.log('✅ Application initialization completed');
        }
        
    } catch (error) {
        console.error('❌ Application initialization failed:', error);
    }
}

// Employee management functions
async function handleEmployeeFormSubmit() {
    /* @tweakable employee form submission debugging */
    const debugEmployeeSubmission = true;
    
    if (debugEmployeeSubmission) {
        console.log('📝 Employee form submitted');
    }
    
    const form = document.getElementById('employeeForm');
    const formData = new FormData(form);
    
    const employeeData = {
        first_name: formData.get('firstName'),
        surname: formData.get('surname'),
        personal_email: formData.get('personalEmail'),
        annual_leave: parseInt(formData.get('annualLeave')) || 15,
        sick_leave: parseInt(formData.get('sickLeave')) || 7
    };
    
    try {
        if (showEmployeeCreationFeedback) {
            showLoading();
        }
        
        if (debugEmployeeSubmission) {
            console.log('🔄 Creating employee record...', employeeData);
        }
        
        const newEmployee = await room.collection('employee').create(employeeData);
        
        if (debugEmployeeSubmission) {
            console.log('✅ Employee created:', newEmployee);
        }
        
        // Reset form
        form.reset();
        
        // Reload employee table
        await loadEmployeeList();
        
        alert(`Employee ${employeeData.first_name} ${employeeData.surname} added successfully!`);
        
    } catch (error) {
        console.error('❌ Error adding employee:', error);
        alert(`Error adding employee: ${error.message}`);
    } finally {
        if (showEmployeeCreationFeedback) {
            hideLoading();
        }
    }
}

async function loadEmployeeList() {
    try {
        const employees = await room.collection('employee').getList();
        loadEmployeeTable(employees);
        populateEmployeeDropdown(employees);
    } catch (error) {
        console.error('Error loading employees:', error);
    }
}

function loadEmployeeTable(employees) {
    const tbody = document.getElementById('employeeTableBody');
    tbody.innerHTML = '';
    
    employees.forEach(employee => {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td>${employee.first_name} ${employee.surname}</td>
            <td>${employee.personal_email}</td>
            <td>${employee.annual_leave}</td>
            <td>${employee.sick_leave}</td>
            <td class="action-buttons">
                <button class="btn btn-secondary" onclick="editEmployee('${employee.id}')">Edit</button>
                <button class="btn btn-danger" onclick="deleteEmployee('${employee.id}')">Delete</button>
            </td>
        `;
        tbody.appendChild(row);
    });
}

function populateEmployeeDropdown(employees) {
    // This would populate a dropdown if we had one
    console.log(`Employee dropdown would be populated with ${employees.length} employees`);
}

function setupEmployeeManagement() {
    /* @tweakable whether to enable employee management setup debugging */
    const debugEmployeeSetup = true;
    
    if (debugEmployeeSetup) {
        console.log('🔧 Setting up employee management handlers...');
    }
    
    // Note: Form handler is already set up in setupCriticalFormHandlers
    // This function can handle additional employee management setup
    
    if (debugEmployeeSetup) {
        console.log('✅ Employee management setup completed');
    }
}

function setupLeaveApplication() {
    console.log('🔧 Setting up leave application handlers...');
}

function setupDateCalculation() {
    /* @tweakable whether to enable automatic date calculation */
    const enableAutoCalculation = true;
    
    const startDate = document.getElementById('startDate');
    const endDate = document.getElementById('endDate');
    
    if (startDate && endDate && enableAutoCalculation) {
        startDate.addEventListener('change', calculateLeaveDuration);
        endDate.addEventListener('change', calculateLeaveDuration);
    }
}

function calculateLeaveDuration() {
    const startDate = document.getElementById('startDate').value;
    const endDate = document.getElementById('endDate').value;
    const durationText = document.getElementById('durationText');
    
    if (startDate && endDate) {
        const start = new Date(startDate);
        const end = new Date(endDate);
        
        if (end >= start) {
            const timeDiff = end.getTime() - start.getTime();
            const dayDiff = Math.ceil(timeDiff / (1000 * 3600 * 24)) + 1;
            durationText.textContent = `Duration: ${dayDiff} day(s)`;
        } else {
            durationText.textContent = 'End date must be after start date';
        }
    } else {
        durationText.textContent = 'Duration will be calculated automatically';
    }
}

function setupLeaveTypeHandling() {
    const checkboxes = document.querySelectorAll('input[name="leaveType"]');
    const reasonTextarea = document.getElementById('reason');
    const reasonNote = document.getElementById('reasonNote');
    
    checkboxes.forEach(checkbox => {
        checkbox.addEventListener('change', function() {
            const anyChecked = Array.from(checkboxes).some(cb => cb.checked);
            
            if (anyChecked) {
                reasonTextarea.disabled = false;
                reasonNote.textContent = 'Please provide details about your leave request.';
            } else {
                reasonTextarea.disabled = true;
                reasonNote.textContent = 'Please select a leave type above to enable this field, or select "Other" to specify a custom reason.';
            }
        });
    });
}

async function submitLeaveApplication(event) {
    event.preventDefault();
    
    try {
        showLoading();
        
        const formData = new FormData(event.target);
        const leaveTypes = Array.from(document.querySelectorAll('input[name="leaveType"]:checked'))
            .map(cb => cb.value);
        
        const applicationData = {
            employee_id: currentUser.id,
            employee_name: `${currentUser.first_name} ${currentUser.surname}`,
            start_date: formData.get('startDate'),
            end_date: formData.get('endDate'),
            start_day_type: formData.get('startDayType'),
            end_day_type: formData.get('endDayType'),
            leave_type: leaveTypes.join(', '),
            selected_reasons: leaveTypes,
            reason: formData.get('reason'),
            total_days: calculateTotalDays(formData.get('startDate'), formData.get('endDate')),
            status: 'Pending'
        };
        
        const result = await room.collection('leave_application').create(applicationData);

        // Show success modal
        document.getElementById('requestId').textContent = result.application_id || result.id;
        document.getElementById('successModal').classList.add('show');

        // Reset form
        event.target.reset();
        calculateLeaveDuration();
        await updateEmployeeInfo();
        
    } catch (error) {
        alert(`Error submitting leave request: ${error.message}`);
    } finally {
        hideLoading();
    }
}

function calculateTotalDays(startDate, endDate) {
    if (!startDate || !endDate) return 0;
    
    const start = new Date(startDate);
    const end = new Date(endDate);
    
    if (end >= start) {
        const timeDiff = end.getTime() - start.getTime();
        return Math.ceil(timeDiff / (1000 * 3600 * 24)) + 1;
    }
    
    return 0;
}

async function loadLeaveApplications() {
    try {
        const applications = await room.collection('leave_application').getList();
        console.log(`Loaded ${applications.length} leave applications`);
    } catch (error) {
        console.error('Error loading leave applications:', error);
    }
}

async function loadLeaveHistory(employeeId) {
    try {
        const apps = await room
            .collection('leave_application')
            .makeRequest('GET', `?employee_id=${encodeURIComponent(employeeId)}`);

        const tbody = document.getElementById('historyTableBody');
        tbody.innerHTML = '';

        apps.forEach(app => {
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${app.application_id || app.id}</td>
                <td>${app.leave_type}</td>
                <td>${app.start_date}</td>
                <td>${app.end_date}</td>
                <td>${app.total_days}</td>
                <td>${app.status}</td>
                <td>${app.date_applied || ''}</td>
                <td>—</td>
            `;
            tbody.appendChild(row);
        });

        if (apps.length === 0) {
            const row = document.createElement('tr');
            row.innerHTML = '<td colspan="8">No leave applications found</td>';
            tbody.appendChild(row);
        }
    } catch (error) {
        console.error('Error loading leave history:', error);
    }
}

async function loadHolidays() {
    try {
        const holidays = await room.collection('holiday').getList();
        console.log(`Loaded ${holidays.length} holidays`);
    } catch (error) {
        console.error('Error loading holidays:', error);
    }
}

function switchTab(tabName) {
    /* @tweakable whether to log tab switching for debugging */
    const logTabSwitching = true;

    if (logTabSwitching) {
        console.log(`🔄 Switching to tab: ${tabName}`);
    }

    // Map hyphenated tab names to their camel-cased button IDs
    const tabButtonIds = {
        'leave-request': 'tabLeaveRequest',
        'check-history': 'tabCheckHistory',
        'employee-management': 'tabEmployeeManagement',
        'application-status': 'tabApplicationStatus',
        'holiday-dates': 'tabHolidayDates'
    };
    
    // Hide all tab contents
    document.querySelectorAll('.tab-content').forEach(tab => {
        tab.classList.remove('active');
    });
    
    // Remove active class from all tab buttons
    document.querySelectorAll('.tab-button').forEach(btn => {
        btn.classList.remove('active');
    });
    
    // Show selected tab content
    const targetTab = document.getElementById(tabName);
    if (targetTab) {
        targetTab.classList.add('active');
    }
    
    // Activate corresponding tab button
    const targetButtonId = tabButtonIds[tabName];
    if (targetButtonId) {
        const targetButton = document.getElementById(targetButtonId);
        if (targetButton) {
            targetButton.classList.add('active');
        }
    }

    // Load leave history when user views the history tab
    if (tabName === 'check-history' && currentUser) {
        loadLeaveHistory(currentUser.id);
    }
}

function filterApplications(status) {
    console.log(`Filtering applications by status: ${status}`);
}

function exportDatabaseBackup() {
    console.log('Export database backup triggered (not implemented)');
}

function importDatabaseBackup() {
    console.log('Import database backup triggered (not implemented)');
}

// Utility functions
async function editEmployee(employeeId) {
    console.log(`Editing employee: ${employeeId}`);
}

async function deleteEmployee(employeeId) {
    if (confirm('Are you sure you want to delete this employee?')) {
        try {
            await room.collection('employee').delete(employeeId);
            await loadEmployeeList();
            alert('Employee deleted successfully');
        } catch (error) {
            alert(`Error deleting employee: ${error.message}`);
        }
    }
}

async function deleteAllEmployees() {
    if (confirm('Are you sure you want to delete ALL employees? This action cannot be undone.')) {
        try {
            const employees = await room.collection('employee').getList();
            
            for (const employee of employees) {
                await room.collection('employee').delete(employee.id);
            }
            
            await loadEmployeeList();
            alert('All employees deleted successfully');
        } catch (error) {
            alert(`Error deleting employees: ${error.message}`);
        }
    }
}

// Modal functions
function closeErrorModal() {
    document.getElementById('errorModal').classList.remove('show');
}

function closeEditModal() {
    document.getElementById('editModal').classList.remove('show');
}

// Close success modal
document.addEventListener('DOMContentLoaded', function() {
    const closeModalBtn = document.getElementById('closeModal');
    if (closeModalBtn) {
        closeModalBtn.addEventListener('click', function() {
            document.getElementById('successModal').classList.remove('show');
        });
    }
});

// Placeholder implementations for future features
function filterApplications(status) {
    console.warn('filterApplications is not implemented yet:', status);
}

function exportDatabaseBackup() {
    console.warn('exportDatabaseBackup is not implemented yet.');
}

function importDatabaseBackup() {
    console.warn('importDatabaseBackup is not implemented yet.');
}

// Expose functions for inline handlers
window.showEmployeeLogin = showEmployeeLogin;
window.showAdminLogin = showAdminLogin;
window.switchTab = switchTab;
window.editEmployee = editEmployee;
window.deleteEmployee = deleteEmployee;
window.deleteAllEmployees = deleteAllEmployees;
window.closeErrorModal = closeErrorModal;
window.closeEditModal = closeEditModal;
window.filterApplications = filterApplications;
window.exportDatabaseBackup = exportDatabaseBackup;
window.importDatabaseBackup = importDatabaseBackup;
