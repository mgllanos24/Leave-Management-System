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
            let controller;
            let timeoutId;
            try {
                controller = new AbortController();
                timeoutId = setTimeout(() => controller.abort(), this.database.requestTimeout);

                const options = {
                    method: method,
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    signal: controller.signal,
                    credentials: 'include'
                };

                if (sessionToken) {
                    options.headers['Authorization'] = `Bearer ${sessionToken}`;
                }
                
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
                if (timeoutId) {
                    clearTimeout(timeoutId);
                }

                if (error.name === 'AbortError') {
                    console.error(`⏱️ ${method} ${url} timed out after ${this.database.requestTimeout}ms`);
                    error = new Error(`Request timed out after ${this.database.requestTimeout}ms`);
                }

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

    async getList(params = {}) {
        const queryString = new URLSearchParams(params).toString();
        try {
            // Check cache validity for unfiltered requests
            const now = Date.now();
            if (!queryString && this.cachedData.length > 0 && now - this.lastFetchTime < this.cacheTimeout) {
                return this.applyFilters(this.cachedData);
            }

            const data = await this.makeRequest('GET', queryString ? `?${queryString}` : '');
            if (!queryString) {
                this.cachedData = data || [];
                this.lastFetchTime = now;
                return this.applyFilters(this.cachedData);
            }

            return this.applyFilters(data || []);
        } catch (error) {
            console.error(`Error fetching ${this.name}:`, error);
            if (!queryString) {
                return this.applyFilters(this.cachedData); // Return cached data on error for unfiltered requests
            }
            return this.applyFilters([]);
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

// Global cache for holiday dates (ISO YYYY-MM-DD)
const holidayDates = new Set();

// Authentication globals
let currentUserType = null;
let currentUser = null;
let sessionToken = null;

// Track whether holiday form handlers have been initialized
let holidayFormInitialized = false;

/* @tweakable sessionStorage keys for authentication persistence */
const AUTH_TYPE_KEY = 'elms_auth_type';
const AUTH_USER_KEY = 'elms_auth_user';
const AUTH_TOKEN_KEY = 'elms_session_token';

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

        const result = await room.collection('leave_balance').update(bal.id, { remaining_days: parseFloat(remaining) });

        // Clear cached balances and refresh employee list
        this.clearEmployeeBalanceCache(employeeId);
        await loadEmployeeList();

        return result;
    }
};

const SERVICE_LENGTH_MAP = {
    '1-3': 5,
    '4-7': 10,
    '8+': 15
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

    initEntryButtons();
    restoreAuthenticationState();
    
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
    const tabAdminHistory = document.getElementById('tabAdminHistory');
    if (tabAdminHistory) {
        tabAdminHistory.addEventListener('click', () => switchTab('admin-history'));
    }
    const resetBtn = document.getElementById('resetBalancesBtn');
    if (resetBtn) resetBtn.addEventListener('click', resetAllLeaveBalances);

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

function updatePrivilegeLeave(rangeId, targetId) {
    const range = document.getElementById(rangeId);
    const target = document.getElementById(targetId);
    if (!range || !target) return;

    const mapping = {
        '1-3': 5,
        '4-7': 10,
        '8+': 15
    };

    target.value = mapping[range.value] || '';
}

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

        const serviceLengthSelect = document.getElementById('serviceLength');
        if (serviceLengthSelect) {
            serviceLengthSelect.addEventListener('change', function() {
                updatePrivilegeLeave('serviceLength', 'annualLeave');
            });

            // Set default PL days based on the initial service length selection
            updatePrivilegeLeave('serviceLength', 'annualLeave');

            if (debugImmediateSetup) {
                console.log('✅ Service length change handler attached immediately');
            }
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

    // Set up edit employee form handler immediately
    const editEmployeeForm = document.getElementById('editEmployeeForm');
    if (editEmployeeForm) {
        editEmployeeForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            e.stopPropagation();

            if (debugImmediateSetup) {
                console.log('✅ Edit employee form submitted via immediate handler');
            }

            try {
                const formData = new FormData(editEmployeeForm);
                const employeeId = editEmployeeForm.dataset.employeeId;

                const updatedData = {
                    first_name: formData.get('editFirstName'),
                    surname: formData.get('editSurname'),
                    personal_email: formData.get('editPersonalEmail'),
                    annual_leave: parseInt(formData.get('editAnnualLeave')) || 0,
                    sick_leave: parseInt(formData.get('editSickLeave')) || 0,
                    remaining_privilege_leave:
                        parseFloat(formData.get('editRemainingPrivilege')) || 0,
                    remaining_sick_leave:
                        parseFloat(formData.get('editRemainingSick')) || 0
                };

                await room.collection('employee').update(employeeId, updatedData);

                await loadEmployeeList();
                await loadEmployeeSummary();
                closeEditModal();
                alert('Employee updated successfully');
            } catch (error) {
                console.error('Error updating employee:', error);
                alert(`Error updating employee: ${error.message}`);
            }
        });

        const editServiceLength = document.getElementById('editServiceLength');
        if (editServiceLength) {
            editServiceLength.addEventListener('change', function() {
                const annualInput = document.getElementById('editAnnualLeave');
                const mapped = SERVICE_LENGTH_MAP[this.value];
                annualInput.value = mapped !== undefined ? mapped : '';
            });
        }

        if (debugImmediateSetup) {
            console.log('✅ Edit employee form submit handler attached immediately');
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
    try {
        const savedType = sessionStorage.getItem(AUTH_TYPE_KEY);
        const savedUser = sessionStorage.getItem(AUTH_USER_KEY);
        const savedToken = sessionStorage.getItem(AUTH_TOKEN_KEY);

        if (savedType && savedUser) {
            const canRestore = savedType === 'admin' || savedToken;
            if (canRestore) {
                currentUserType = savedType;
                currentUser = JSON.parse(savedUser);
                sessionToken = savedToken;

                if (debugAuthRestore) {
                    console.log('✅ Authentication state restored:', { type: currentUserType, user: currentUser });
                }
                showMainApp();
            }
        }
    } catch (error) {
        console.error('Error restoring auth state:', error);
        clearPersistedAuthState();
    }
}

function clearPersistedAuthState() {
    /* @tweakable whether to clear all auth-related sessionStorage items */
    const clearAllAuthData = true;

    if (clearAllAuthData) {
        sessionStorage.removeItem(AUTH_TYPE_KEY);
        sessionStorage.removeItem(AUTH_USER_KEY);
        sessionStorage.removeItem(AUTH_TOKEN_KEY);
    }
}

// Show functions
function showEntrySelection() {
    document.getElementById('entryContainer').style.display = 'block';
    document.getElementById('employeeLoginContainer').style.display = 'none';
    document.getElementById('adminLoginContainer').style.display = 'none';
    document.getElementById('appContainer').style.display = 'none';
}

function initEntryButtons() {
    const employeeBtn = document.getElementById('employeeEntryBtn');
    const adminBtn = document.getElementById('adminEntryBtn');

    if (employeeBtn) {
        employeeBtn.addEventListener('click', showEmployeeLogin);
    } else {
        console.error('employeeEntryBtn not found');
    }

    if (adminBtn) {
        adminBtn.addEventListener('click', showAdminLogin);
    } else {
        console.error('adminEntryBtn not found');
    }
}

initEntryButtons();

function showEmployeeLogin() {
    /* @tweakable whether to log navigation to employee login */
    const logNavigation = true;

    if (logNavigation) {
        console.log('🔄 Navigating to employee login');
    }

    const employeeForm = document.getElementById('loginEmployeeForm');
    if (employeeForm) {
        employeeForm.reset();
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

    const adminForm = document.getElementById('loginAdminForm');
    if (adminForm) {
        adminForm.reset();
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
            // Request a server-generated ID for consistency with stored applications
            const resp = await fetch('/api/next_application_id', {
                headers: sessionToken ? { 'Authorization': `Bearer ${sessionToken}` } : {},
                credentials: 'include'
            });
            if (resp.ok) {
                const data = await resp.json();
                previewId = data.application_id || previewId;
            }
        } catch (err) {
            // Use generated previewId on error or if endpoint not available
        }
        idPreviewEl.textContent = previewId;
    }

    // Update leave balance display for logged in employee
    if (currentUser && currentUser.id) {
        await updateLeaveBalanceDisplay();
    }
}

// Fetch and render remaining leave balances for the current employee
async function updateLeaveBalanceDisplay() {
    const container = document.getElementById('leaveBalanceDisplay');
    if (!currentUser || !container) {
        return;
    }

    try {
        const resp = await fetch(`/api/leave_balance?employee_id=${currentUser.id}`, {
            headers: sessionToken ? { 'Authorization': `Bearer ${sessionToken}` } : {},
            credentials: 'include'
        });
        if (!resp.ok) throw new Error('Failed to fetch leave balances');
        const balances = await resp.json();

        const priv = balances.find(b => b.balance_type === 'PRIVILEGE');
        const sick = balances.find(b => b.balance_type === 'SICK');

        const privEl = document.getElementById('privilegeLeaveBalance');
        const sickEl = document.getElementById('sickLeaveBalance');
        if (privEl) {
            privEl.textContent = priv ? `${priv.remaining_days} days` : '-- days';
        }
        if (sickEl) {
            sickEl.textContent = sick ? `${sick.remaining_days} days` : '-- days';
        }

        container.style.display = 'block';
    } catch (err) {
        console.error('Error loading leave balances:', err);
        container.style.display = 'none';
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
            body: JSON.stringify({ email: email }),
            credentials: 'include'
        });
        
        if (!response.ok) {
            throw new Error(`Login failed: ${response.status}`);
        }
        
        const data = await response.json();

        currentUserType = 'employee';
        currentUser = data.employee;
        sessionToken = data.token || data.sessionToken || null;
        await updateEmployeeInfo();

        sessionStorage.setItem(AUTH_TYPE_KEY, currentUserType);
        sessionStorage.setItem(AUTH_USER_KEY, JSON.stringify(currentUser));
        if (sessionToken) {
            sessionStorage.setItem(AUTH_TOKEN_KEY, sessionToken);
        }
        
        hideLoading();
        showMainApp();
        
    } catch (error) {
        hideLoading();
        alert(`Login failed: ${error.message}`);
    }
}

async function loginAdmin(username, password) {
    try {
        showLoading();

        const resp = await fetch('/api/login_admin', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ username, password })
        });

        if (!resp.ok) {
            throw new Error('Invalid credentials');
        }

        currentUserType = 'admin';
        currentUser = { username: username, first_name: 'Administrator', email: 'admin@company.com' };
        sessionToken = null;
        sessionStorage.setItem(AUTH_TYPE_KEY, currentUserType);
        sessionStorage.setItem(AUTH_USER_KEY, JSON.stringify(currentUser));
        sessionStorage.removeItem(AUTH_TOKEN_KEY);

        hideLoading();
        showMainApp();
    } catch (error) {
        hideLoading();
        alert(`Login failed: ${error.message}`);
    }
}

async function logoutAdmin() {
    try {
        await fetch('/api/logout_admin', {
            method: 'POST',
            credentials: 'include'
        });
    } catch (error) {
        console.error('Error logging out admin:', error);
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
    document.getElementById('tabAdminHistory').style.display = isAdmin ? 'block' : 'none';
    document.getElementById('adminSection').style.display = isAdmin ? 'block' : 'none';

    // Toggle visibility for employee-specific tabs based on user role
    document.getElementById('tabLeaveRequest').style.display = isAdmin ? 'none' : 'block';
    document.getElementById('tabCheckHistory').style.display = isAdmin ? 'none' : 'block';

    // Hide tab content sections that shouldn't be visible for the current role
    document.getElementById('employee-management').style.display = isAdmin ? '' : 'none';
    document.getElementById('application-status').style.display = isAdmin ? '' : 'none';
    document.getElementById('holiday-dates').style.display = isAdmin ? '' : 'none';
    document.getElementById('admin-history').style.display = isAdmin ? '' : 'none';
    document.getElementById('leave-request').style.display = isAdmin ? 'none' : '';
    document.getElementById('check-history').style.display = isAdmin ? 'none' : '';

    // Ensure the active tab is one the user can access
    const activeTab = document.querySelector('.tab-content.active');
    if (activeTab && activeTab.style.display === 'none') {
        switchTab(isAdmin ? 'employee-management' : 'leave-request');
    }
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

async function logout() {
    if (currentUserType === 'admin') {
        await logoutAdmin();
    }

    currentUserType = null;
    currentUser = null;
    sessionToken = null;
    clearPersistedAuthState();

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
        await loadEmployeeSummary();
        await loadHolidays();

        const populateBtn = document.getElementById('populateHolidaysBtn');
        if (populateBtn) {
            populateBtn.addEventListener('click', async () => {
                const confirmPopulate = confirm('Auto-populate holidays for the next fiscal year? This will replace existing holidays.');
                if (confirmPopulate) {
                    await populateNextFiscalYearHolidays();
                }
            });
        }

        // Set up form handlers and other functionality
        setupEmployeeManagement();
        setupHolidayManagement();
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
        sick_leave: parseInt(formData.get('sickLeave')) || 5
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
        updatePrivilegeLeave('serviceLength', 'annualLeave');
        
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
        // Fetch employees and all leave balance records in parallel
        const [employees, balances] = await Promise.all([
            room.collection('employee').getList(),
            room.collection('leave_balance').getList()
        ]);

        // Merge balance information with each employee
        const mergedEmployees = employees.map(emp => {
            const empBalances = balances.filter(b => b.employee_id === emp.id);
            const privilege = empBalances.find(b => b.balance_type === 'PRIVILEGE');
            const sick = empBalances.find(b => b.balance_type === 'SICK');
            return {
                ...emp,
                privilege_remaining: privilege ? privilege.remaining_days : 0,
                sick_remaining: sick ? sick.remaining_days : 0
            };
        });

        loadEmployeeTable(mergedEmployees);
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
            <td>${employee.privilege_remaining}</td>
            <td>${employee.sick_remaining}</td>
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

function setupHolidayManagement() {
    /* @tweakable whether to enable holiday management setup debugging */
    const debugHolidaySetup = true;

    if (debugHolidaySetup) {
        console.log('🔧 Setting up holiday management handlers...');
    }

    // Only attach handlers once
    if (holidayFormInitialized) {
        if (debugHolidaySetup) {
            console.log('ℹ️ Holiday form handlers already initialized');
        }
        return;
    }

    const holidayForm = document.getElementById('holidayForm');
    if (holidayForm) {
        holidayForm.addEventListener('submit', async function(e) {
            e.preventDefault();

            const date = document.getElementById('holidayDate').value;
            const name = document.getElementById('holidayName').value;

            try {
                await room.collection('holiday').create({ date, name });
                holidayForm.reset();
                await loadHolidays();
            } catch (error) {
                console.error('Error adding holiday:', error);
                alert('Failed to add holiday: ' + (error.message || 'Unknown error'));
            }
        });

        holidayFormInitialized = true;

        if (debugHolidaySetup) {
            console.log('✅ Holiday form submit handler attached');
        }
    }

    if (debugHolidaySetup) {
        console.log('✅ Holiday management setup completed');
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
    const startDayRadios = document.querySelectorAll('input[name="startDayType"]');
    const endDayRadios = document.querySelectorAll('input[name="endDayType"]');

    if (startDate && endDate && enableAutoCalculation) {
        startDate.addEventListener('change', calculateLeaveDuration);
        endDate.addEventListener('change', calculateLeaveDuration);
        startDayRadios.forEach(radio => radio.addEventListener('change', calculateLeaveDuration));
        endDayRadios.forEach(radio => radio.addEventListener('change', calculateLeaveDuration));
    }
}

function calculateLeaveDuration() {
    const startDate = document.getElementById('startDate').value;
    const endDate = document.getElementById('endDate').value;
    const durationText = document.getElementById('durationText');
    const startDayType = document.querySelector('input[name="startDayType"]:checked')?.value || 'full';
    const endDayType = document.querySelector('input[name="endDayType"]:checked')?.value || 'full';

    if (startDate && endDate) {
        const start = new Date(startDate);
        const end = new Date(endDate);

        if (end >= start) {
            const dayDiff = calculateTotalDays(startDate, endDate, startDayType, endDayType);
            durationText.textContent = `Duration: ${dayDiff} day(s)`;
        } else {
            durationText.textContent = 'End date must be after start date';
        }
    } else {
        durationText.textContent = 'Duration will be calculated automatically';
    }
}

function setupLeaveTypeHandling() {
    const radios = document.querySelectorAll('input[name="leaveType"]');
    const reasonTextarea = document.getElementById('reason');
    const reasonNote = document.getElementById('reasonNote');

    radios.forEach(radio => {
        radio.addEventListener('change', function() {
            const anyChecked = Array.from(radios).some(rb => rb.checked);

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
        const selectedLeaveType = formData.get('leaveType');

    const applicationData = {
        employee_id: currentUser.id,
        employee_name: `${currentUser.first_name} ${currentUser.surname}`,
        start_date: formData.get('startDate'),
        end_date: formData.get('endDate'),
        start_day_type: formData.get('startDayType'),
        end_day_type: formData.get('endDayType'),
        leave_type: selectedLeaveType,
        selected_reasons: selectedLeaveType ? [selectedLeaveType] : [],
        reason: formData.get('reason'),
        total_days: calculateTotalDays(
            formData.get('startDate'),
            formData.get('endDate'),
            formData.get('startDayType'),
            formData.get('endDayType')
        ),
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

function calculateTotalDays(startDate, endDate, startDayType, endDayType) {
    if (!startDate || !endDate) return 0;

    const start = new Date(startDate);
    const end = new Date(endDate);
    if (end < start) return 0;

    const startType = startDayType || document.querySelector('input[name="startDayType"]:checked')?.value || 'full';
    const endType = endDayType || document.querySelector('input[name="endDayType"]:checked')?.value || 'full';

    let total = 0;
    const current = new Date(start);
    while (current <= end) {
        const iso = current.toISOString().split('T')[0];
        const day = current.getDay();
        // Skip weekends (Saturday=6, Sunday=0)
        if (day !== 0 && day !== 6 && !holidayDates.has(iso)) {
            total += 1;
            if (current.getTime() === start.getTime() && startType !== 'full') {
                total -= 0.5;
            }
            if (current.getTime() === end.getTime() && endType !== 'full') {
                total -= 0.5;
            }
        }
        current.setDate(current.getDate() + 1);
    }

    return total;
}

async function loadLeaveApplications() {
    try {
        const applications = await room.collection('leave_application').getList({ status: 'Pending' });

        const tbody = document.getElementById('applicationsTableBody');
        if (!tbody) {
            console.warn('applicationsTableBody element not found');
            return;
        }
        tbody.innerHTML = '';

        applications.forEach(app => {
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${app.application_id || app.id}</td>
                <td>${app.employee_name || app.employee_id}</td>
                <td>${app.leave_type}</td>
                <td>${app.start_date}</td>
                <td>${app.end_date}</td>
                <td>${app.total_days}</td>
                <td>${app.status}</td>
                <td class="application-actions">
                    <button class="approve-btn">Approve</button>
                    <button class="reject-btn">Reject</button>
                </td>
            `;
            tbody.appendChild(row);

            const approveBtn = row.querySelector('.approve-btn');
            if (approveBtn) {
                approveBtn.addEventListener('click', () =>
                    updateApplicationStatus(app.id ?? app.application_id, 'Approved')
                );
            }
            const rejectBtn = row.querySelector('.reject-btn');
            if (rejectBtn) {
                rejectBtn.addEventListener('click', () =>
                    updateApplicationStatus(app.id ?? app.application_id, 'Rejected')
                );
            }
        });

        if (applications.length === 0) {
            const row = document.createElement('tr');
            row.innerHTML = '<td colspan="8">No leave applications found</td>';
            tbody.appendChild(row);
        }

    } catch (error) {
        console.error('Error loading leave applications:', error);
    }
}

// Load summary of employee leave usage and balances
async function loadEmployeeSummary() {
    try {
        const [employees, balances, applications] = await Promise.all([
            room.collection('employee').getList(),
            room.collection('leave_balance').getList(),
            room.collection('leave_application').getList()
        ]);

        const searchInput = document.getElementById('employeeSearch');
        const filter = searchInput ? searchInput.value.trim().toLowerCase() : '';

        const summary = new Map();

        employees.forEach(emp => {
            const name = emp.first_name
                ? `${emp.first_name} ${emp.surname || ''}`.trim()
                : emp.employee_name || emp.username || emp.email || emp.id;
            summary.set(emp.id, {
                name,
                privilegeAllocated: 0,
                privilegeUsed: 0,
                privilegeRemaining: 0,
                sickAllocated: 0,
                sickUsed: 0,
                sickRemaining: 0,
                activeRequests: 0
            });
        });

        balances.forEach(bal => {
            const info = summary.get(bal.employee_id);
            if (!info) return;
            const allocated = (parseFloat(bal.allocated_days) || 0) +
                (parseFloat(bal.carryforward_days) || 0);
            const remaining = parseFloat(bal.remaining_days) || 0;

            if (bal.balance_type === 'PRIVILEGE') {
                info.privilegeAllocated = allocated;
                info.privilegeRemaining = remaining;
            } else if (bal.balance_type === 'SICK') {
                info.sickAllocated = allocated;
                info.sickRemaining = remaining;
            }
        });

        applications.forEach(app => {
            const info = summary.get(app.employee_id);
            if (!info) return;

            const type = (app.leave_type || '').trim().toLowerCase();
            const days = parseFloat(app.total_days) || 0;

            if (app.status === 'Pending') {
                info.activeRequests += 1;
                return;
            }

            if (app.status === 'Approved') {
                const privilegeTypes = ['privilege', 'pl', 'vacation-annual', 'personal'];
                const sickTypes = ['sick', 'sl'];

                if (privilegeTypes.includes(type)) {
                    info.privilegeUsed += days;
                } else if (sickTypes.includes(type)) {
                    info.sickUsed += days;
                }
            }
        });

        summary.forEach(info => {
            if (info.privilegeAllocated && info.privilegeRemaining == null) {
                info.privilegeRemaining = info.privilegeAllocated - info.privilegeUsed;
            }
            if (info.sickAllocated && info.sickRemaining == null) {
                info.sickRemaining = info.sickAllocated - info.sickUsed;
            }
        });

        const tbody = document.getElementById('employeeStatusTableBody');
        if (!tbody) {
            console.warn('employeeStatusTableBody element not found');
            return;
        }
        tbody.innerHTML = '';

        let hasRows = false;
        for (const info of summary.values()) {
            if (filter && !info.name.toLowerCase().includes(filter)) continue;
            const row = document.createElement('tr');
            const pClass = info.privilegeRemaining <= 0 ? "remaining-alert" : "";
            const sClass = info.sickRemaining <= 0 ? "remaining-alert" : "";
            row.innerHTML = `
                <td>${info.name}</td>
                <td>${info.privilegeAllocated}</td>
                <td>${info.privilegeUsed}</td>
                <td class="${pClass}">${info.privilegeRemaining}</td>
                <td>${info.sickAllocated}</td>
                <td>${info.sickUsed}</td>
                <td class="${sClass}">${info.sickRemaining}</td>
                <td>${info.activeRequests}</td>
            `;
            tbody.appendChild(row);
            hasRows = true;
        }

        if (!hasRows) {
            const row = document.createElement('tr');
            row.innerHTML = '<td colspan="8">No employee data found</td>';
            tbody.appendChild(row);
        }
    } catch (error) {
        console.error('Error loading employee summary:', error);
    }
}

async function updateApplicationStatus(id, newStatus) {
    showLoading();

    // Disable all action buttons to prevent duplicate requests
    const actionButtons = document.querySelectorAll('.approve-btn, .reject-btn');
    actionButtons.forEach(btn => (btn.disabled = true));

    try {
        await room.collection('leave_application').update(id, { status: newStatus });
        await loadLeaveApplications();
        await loadEmployeeSummary();
        await loadEmployeeList();
        alert('Application status updated successfully');
    } catch (error) {
        const requestUrl = `leave_application/${id}`;
        const status = error?.response?.status || error.status;
        let responseBody = '';

        if (error?.response) {
            try {
                responseBody = await error.response.text();
            } catch (e) {
                responseBody = error?.response?.body || e.message;
            }
        } else {
            responseBody = error.message;
        }

        console.error('Error updating application status:', {
            requestUrl,
            status,
            responseBody,
            originalError: error,
        });
        alert(`Failed to update application status for ID ${id}. ${status ? `Status: ${status}.` : ''}`);
    } finally {
        actionButtons.forEach(btn => (btn.disabled = false));
        hideLoading();
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
            `;
            tbody.appendChild(row);
        });

        if (apps.length === 0) {
            const row = document.createElement('tr');
            row.innerHTML = '<td colspan="6">No leave applications found</td>';
            tbody.appendChild(row);
        }
    } catch (error) {
        console.error('Error loading leave history:', error);
    }
}

async function loadAdminLeaveHistory(search = '', startMonth = '', endMonth = '') {
    const container = document.getElementById('weeklyHistory');
    if (!container) return;
    container.innerHTML = '';
    try {
        const year = new Date().getFullYear();
        const startDate = startMonth
            ? new Date(year, parseInt(startMonth) - 1, 1)
            : new Date(year, 0, 1);
        const endDate = endMonth
            ? new Date(year, parseInt(endMonth), 0)
            : new Date(year, 11, 31);

        const apps = await room.collection('leave_application').getList({ status: 'Approved' });

        const filtered = apps.filter(app => {
            const nameMatch = app.employee_name?.toLowerCase().includes(search.toLowerCase());
            const appStart = new Date(app.start_date);
            const appEnd = new Date(app.end_date);
            const inRange = appStart >= startDate && appEnd <= endDate;
            return nameMatch && inRange;
        });

        filtered.sort((a, b) => a.employee_name.localeCompare(b.employee_name));

        const groups = {};
        filtered.forEach(app => {
            const start = new Date(app.start_date);
            const day = start.getDay();
            const diff = day === 0 ? -6 : 1 - day; // shift to Monday
            const monday = new Date(start);
            monday.setDate(start.getDate() + diff);
            const key = monday.toISOString().slice(0, 10);
            if (!groups[key]) groups[key] = [];
            groups[key].push(app);
        });

        Object.keys(groups)
            .sort((a, b) => new Date(b) - new Date(a))
            .forEach(key => {
                const weekApps = groups[key];
                const start = new Date(key);
                const end = new Date(start);
                end.setDate(start.getDate() + 6);

                const details = document.createElement('details');
                details.className = 'week-group';

                const summary = document.createElement('summary');
                summary.textContent = `${key} to ${end.toISOString().slice(0, 10)} (${weekApps.length} records)`;
                details.appendChild(summary);

                const table = document.createElement('table');
                const thead = document.createElement('thead');
                thead.innerHTML = '<tr><th>Employee</th><th>Leave Type</th><th>Dates</th></tr>';
                table.appendChild(thead);
                const tbody = document.createElement('tbody');

                weekApps.forEach(app => {
                    const tr = document.createElement('tr');
                    tr.innerHTML = `<td>${app.employee_name}</td><td>${app.leave_type}</td><td>${app.start_date} - ${app.end_date}</td>`;
                    tbody.appendChild(tr);
                });

                table.appendChild(tbody);
                details.appendChild(table);
                container.appendChild(details);
            });
    } catch (error) {
        console.error('Error loading admin leave history:', error);
    }
}

async function loadHolidays() {
    try {
        const tbody = document.getElementById('holidayTableBody');
        if (tbody) {
            tbody.innerHTML = '';
        }

        const holidays = await room.collection('holiday').getList();

        // Populate global holiday date cache
        holidayDates.clear();
        for (const h of holidays) {
            if (h.date) {
                holidayDates.add(h.date);
            }
        }

        if (tbody) {
            if (holidays.length === 0) {
                const row = document.createElement('tr');
                row.innerHTML = '<td colspan="3">No holidays found</td>';
                tbody.appendChild(row);
            } else {
                holidays.sort((a, b) => new Date(a.date) - new Date(b.date));
                for (const holiday of holidays) {
                    const row = document.createElement('tr');
                    const dateCell = document.createElement('td');
                    dateCell.textContent = holiday.date;
                    const nameCell = document.createElement('td');
                    nameCell.textContent = holiday.name;
                    const actionCell = document.createElement('td');
                    const delBtn = document.createElement('button');
                    delBtn.textContent = 'Delete';
                    delBtn.className = 'btn btn-danger';
                    delBtn.addEventListener('click', async () => {
                        if (confirm('Delete this holiday?')) {
                            await room.collection('holiday').delete(holiday.id);
                            await loadHolidays();
                        }
                    });
                    actionCell.appendChild(delBtn);
                    row.appendChild(dateCell);
                    row.appendChild(nameCell);
                    row.appendChild(actionCell);
                    tbody.appendChild(row);
                }
            }
        }
    } catch (error) {
        console.error('Error loading holidays:', error);
    }
}

function getLastWeekdayOfMonth(year, month, weekday) {
    const lastDay = new Date(year, month + 1, 0);
    const diff = (lastDay.getDay() - weekday + 7) % 7;
    return new Date(year, month, lastDay.getDate() - diff);
}

function getFirstWeekdayOfMonth(year, month, weekday) {
    const firstDay = new Date(year, month, 1);
    const diff = (weekday - firstDay.getDay() + 7) % 7;
    return new Date(year, month, 1 + diff);
}

function formatDate(date) {
    return date.toISOString().split('T')[0];
}

async function populateNextFiscalYearHolidays() {
    const year = new Date().getFullYear() + 1;
    const holidays = [
        { date: `${year}-01-01`, name: 'New Years Day' },
        { date: formatDate(getLastWeekdayOfMonth(year, 4, 1)), name: 'Memorial Day' },
        { date: `${year}-07-04`, name: 'Independence Day' },
        { date: formatDate(getFirstWeekdayOfMonth(year, 8, 1)), name: 'Labor Day' },
        { date: formatDate(getLastWeekdayOfMonth(year, 10, 4)), name: 'Thanksgiving Day' },
        { date: `${year}-12-25`, name: 'Christmas Day' }
    ];

    try {
        await fetch('/api/holiday/auto_populate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ holidays })
        });
        await loadHolidays();
    } catch (error) {
        console.error('Error populating holidays:', error);
        alert('Failed to auto-populate holidays');
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
        'holiday-dates': 'tabHolidayDates',
        'admin-history': 'tabAdminHistory'
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

    // Load tab-specific data when needed
    if (tabName === 'check-history' && currentUser) {
        loadLeaveHistory(currentUser.id);
    } else if (tabName === 'application-status') {
        loadEmployeeSummary();
        loadLeaveApplications();
    } else if (tabName === 'admin-history') {
        const search = document.getElementById('historySearch')?.value || '';
        const start = document.getElementById('historyStartMonth')?.value || '';
        const end = document.getElementById('historyEndMonth')?.value || '';
        loadAdminLeaveHistory(search, start, end);
    }
}

// Utility functions
async function editEmployee(employeeId) {
    try {
        const employees = await room.collection('employee').getList();
        const employee = employees.find(e => e.id === employeeId);
        if (!employee) {
            alert('Employee not found');
            return;
        }

        const form = document.getElementById('editEmployeeForm');
        form.dataset.employeeId = employeeId;

        document.getElementById('editFirstName').value = employee.first_name || '';
        document.getElementById('editSurname').value = employee.surname || '';
        document.getElementById('editPersonalEmail').value = employee.personal_email || '';
        document.getElementById('editAnnualLeave').value = employee.annual_leave || 0;
        document.getElementById('editSickLeave').value = employee.sick_leave || 0;

        const serviceSelect = document.getElementById('editServiceLength');
        if (serviceSelect) {
            let lengthValue = '8+';
            if (employee.annual_leave === 5) {
                lengthValue = '1-3';
            } else if (employee.annual_leave === 10) {
                lengthValue = '4-7';
            }
            serviceSelect.value = lengthValue;
        }

        const balances = await LeaveBalanceAPI.getEmployeeBalances(employeeId);
        const priv = balances.find(b => b.balance_type === 'PRIVILEGE');
        const sick = balances.find(b => b.balance_type === 'SICK');
        document.getElementById('editRemainingPrivilege').value = priv ? priv.remaining_days : 0;
        document.getElementById('editRemainingSick').value = sick ? sick.remaining_days : 0;

        document.getElementById('editModal').classList.add('show');
    } catch (error) {
        console.error('Error editing employee:', error);
        alert(`Error editing employee: ${error.message}`);
    }
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

async function resetAllLeaveBalances() {
    if (confirm('Are you sure you want to reset all leave balances? This action cannot be undone.')) {
        try {
            const resp = await fetch('/api/reset_balances', {
                method: 'POST',
                credentials: 'include'
            });
            if (!resp.ok) throw new Error('Request failed');
            await loadEmployeeList();
            await loadEmployeeSummary();
            alert('All leave balances reset successfully');
        } catch (error) {
            alert(`Error resetting leave balances: ${error.message}`);
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

document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.getElementById('employeeSearch');
    if (searchInput) {
        searchInput.addEventListener('input', loadEmployeeSummary);
    }
});

document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.getElementById('historySearch');
    const startMonth = document.getElementById('historyStartMonth');
    const endMonth = document.getElementById('historyEndMonth');

    const reload = () => {
        const search = searchInput?.value || '';
        const start = startMonth?.value || '';
        const end = endMonth?.value || '';
        loadAdminLeaveHistory(search, start, end);
    };

    if (searchInput) searchInput.addEventListener('input', reload);
    if (startMonth) startMonth.addEventListener('change', reload);
    if (endMonth) endMonth.addEventListener('change', reload);
});

// Expose functions for inline handlers
window.showEmployeeLogin = showEmployeeLogin;
window.showAdminLogin = showAdminLogin;
window.switchTab = switchTab;
window.editEmployee = editEmployee;
window.deleteEmployee = deleteEmployee;
window.resetAllLeaveBalances = resetAllLeaveBalances;
window.closeErrorModal = closeErrorModal;
window.closeEditModal = closeEditModal;
window.updateApplicationStatus = updateApplicationStatus;
window.loadEmployeeSummary = loadEmployeeSummary;
