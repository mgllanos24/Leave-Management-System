import json
import subprocess
from pathlib import Path


def test_leave_history_renders_unpaid_hours_when_paid_is_less_than_total():
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "script.js"

    node_script = """
const fs = require('fs');
const code = fs.readFileSync(__SCRIPT_PATH__, 'utf8');
const originalLog = console.log;
console.log = () => {};

global.window = global;
window.location = { href: 'http://localhost/', search: '' };
window.addEventListener = () => {};

function createClassList() {
  return { add() {}, remove() {} };
}

class Element {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this._innerHTML = '';
    this.attributes = {};
    this.classList = createClassList();
    this.style = {};
    this.dataset = {};
    this.value = '';
  }

  set innerHTML(value) {
    this._innerHTML = value;
    this.children = [];
    if (this.appended) {
      this.appended = [];
    }
  }

  get innerHTML() {
    return this._innerHTML;
  }

  appendChild(child) {
    this.children.push(child);
  }

  querySelectorAll() {
    return [];
  }

  querySelector() {
    return null;
  }

  addEventListener() {}

  removeEventListener() {}

  setAttribute(name, value) {
    this.attributes[name] = value;
  }

  get textContent() {
    return this._innerHTML;
  }

  set textContent(value) {
    this._innerHTML = value;
  }
}

const tbody = new Element('tbody');
tbody.appended = [];
const originalAppendChild = tbody.appendChild.bind(tbody);
tbody.appendChild = child => {
  originalAppendChild(child);
  tbody.appended.push(child);
};

const elementsById = {
  employeeHistoryTableBody: tbody,
};

global.document = {
  createElement: tag => new Element(tag),
  getElementById: id => elementsById[id] || new Element('div'),
  querySelectorAll: () => [],
  querySelector: () => null,
  addEventListener: () => {},
};

document.body = new Element('body');

global.alert = () => {};
global.confirm = () => true;
global.fetch = async () => ({ ok: true, json: async () => ({}), text: async () => '' });
global.sessionStorage = {
  getItem: () => null,
  setItem: () => {},
  removeItem: () => {},
};
global.localStorage = {
  getItem: () => null,
  setItem: () => {},
  removeItem: () => {},
};
global.AbortController = class {
  constructor() {
    this.signal = {};
  }

  abort() {}
};
global.FormData = class {
  constructor(form) {
    this._data = form && typeof form.getFormData === 'function' ? form.getFormData() : {};
  }

  append() {}

  get(name) {
    return this._data.hasOwnProperty(name) ? this._data[name] : null;
  }
};
global.File = class {};
global.navigator = { userAgent: 'node' };

eval(code);
console.log = originalLog;

const backendRoom = window.room;

const applications = [
  {
    id: '101',
    application_id: 'APP-101',
    total_hours: 8,
    start_date: '2024-01-01',
    end_date: '2024-01-01',
    start_time: '06:30',
    end_time: '15:00',
    leave_type: 'Privilege Leave',
    status: 'Approved',
  },
];

const balanceHistory = [
  {
    employee_id: 'emp-1',
    application_id: '101',
    change_type: 'DEDUCTION',
    balance_type: 'PRIVILEGE',
    change_amount: -0.5,
    previous_balance: 0.5,
  },
];

backendRoom.collection = name => ({
  makeRequest() {
    if (name === 'leave_application') return Promise.resolve(applications);
    if (name === 'leave_balance_history') return Promise.resolve(balanceHistory);
    return Promise.resolve([]);
  },
  getList() {
    return this.makeRequest('GET');
  },
});

(async () => {
  await loadLeaveHistory('emp-1');
  if (!tbody.appended.length) {
    throw new Error('Expected at least one row to be rendered');
  }
  const firstRow = tbody.appended[0];
  const cells = firstRow.innerHTML
    .split('</td>')
    .filter(Boolean)
    .map(segment => segment.replace(/^.*?>/s, '').trim());

  const result = {
    cellCount: cells.length,
    leaveLabel: cells[1] || null,
    unpaidCell: cells[6] || null,
  };

  originalLog(JSON.stringify(result));
})().catch(error => {
  originalLog(JSON.stringify({ error: error.message }));
  process.exit(1);
});
"""

    node_script = node_script.replace("__SCRIPT_PATH__", json.dumps(str(script_path)))

    completed = subprocess.run(
        ["node", "-e", node_script],
        check=True,
        capture_output=True,
        text=True,
    )

    output = completed.stdout.strip()
    assert output, completed.stderr

    result = json.loads(output)
    assert result.get("cellCount") >= 8
    assert result.get("leaveLabel") == "Unpaid Leave"
    assert result.get("unpaidCell") == "4.00 h"


def test_privilege_leave_partial_request_triggers_alert_message():
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "script.js"

    node_script = """
const fs = require('fs');
const vm = require('vm');
const code = fs.readFileSync(__SCRIPT_PATH__, 'utf8');

function createClassList() {
  return { add() {}, remove() {} };
}

class Element {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this._innerHTML = '';
    this.attributes = {};
    this.classList = createClassList();
    this.style = {};
    this.dataset = {};
    this.value = '';
  }

  set innerHTML(value) {
    this._innerHTML = value;
    this.children = [];
  }

  get innerHTML() {
    return this._innerHTML;
  }

  appendChild(child) {
    this.children.push(child);
  }

  querySelectorAll() {
    return [];
  }

  querySelector() {
    return null;
  }

  addEventListener() {}

  removeEventListener() {}

  setAttribute(name, value) {
    this.attributes[name] = value;
  }

  get textContent() {
    return this._innerHTML;
  }

  set textContent(value) {
    this._innerHTML = value;
  }
}

const alerts = [];

const durationText = new Element('div');
const startTime = new Element('input');
startTime.value = '06:30';
const endTime = new Element('input');
endTime.value = '15:00';
const startDate = new Element('input');
startDate.value = '2024-01-01';
const endDate = new Element('input');
endDate.value = '2024-01-01';
const loadingOverlay = new Element('div');
const requestId = new Element('span');
const successModal = new Element('div');
successModal.classList = createClassList();

const elementsById = {
  durationText,
  startTime,
  endTime,
  startDate,
  endDate,
  loadingOverlay,
  requestId,
  successModal,
};

const document = {
  createElement: tag => new Element(tag),
  getElementById: id => elementsById[id] || new Element('div'),
  querySelectorAll: () => [],
  querySelector: () => null,
  addEventListener: () => {},
};

document.body = new Element('body');

const context = {
  console: { log: () => {}, warn: () => {}, error: () => {} },
  setTimeout,
  clearTimeout,
  document,
  location: { href: 'http://localhost/', search: '' },
  addEventListener: () => {},
  alert: message => alerts.push(message),
  confirm: () => true,
  fetch: async () => ({ ok: true, json: async () => ({}), text: async () => '' }),
  sessionStorage: {
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {},
  },
  localStorage: {
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {},
  },
  AbortController: class {
    constructor() {
      this.signal = {};
    }

    abort() {}
  },
  FormData: class {
    constructor(form) {
      this._data = form && typeof form.getFormData === 'function' ? form.getFormData() : {};
    }

    append() {}

    get(name) {
      return Object.prototype.hasOwnProperty.call(this._data, name) ? this._data[name] : null;
    }
  },
  File: class {},
  navigator: { userAgent: 'node' },
};

context.window = context;
context.global = context;
context.document = document;
context.confirm = () => true;

vm.createContext(context);
vm.runInContext(code, context);

context.room.collection = name => ({
  create: async () => ({ application_id: 'APP-500' }),
});

context.calculateLeaveDuration = () => {};
context.updateEmployeeInfo = async () => {};

vm.runInContext('currentPrivilegeRemainingDays = 0.5; currentUser = { id: "emp-2", first_name: "Test", surname: "User" };', context);

const leaveForm = {
  getFormData() {
    return {
      leaveType: 'leave-without-pay',
      startDate: '2024-01-01',
      endDate: '2024-01-01',
      startTime: '06:30',
      endTime: '15:00',
      reason: 'Testing partial coverage',
    };
  },
  reset() {},
};

const event = {
  preventDefault() {},
  target: leaveForm,
};

(async () => {
  await context.submitLeaveApplication(event);
  const result = {
    alertCount: alerts.length,
    lastAlert: alerts.length ? alerts[alerts.length - 1] : null,
  };
  console.log(JSON.stringify(result));
})().catch(error => {
  console.log(JSON.stringify({ error: error.message }));
  process.exit(1);
});
"""

    node_script = node_script.replace("__SCRIPT_PATH__", json.dumps(str(script_path)))

    completed = subprocess.run(
        ["node", "-e", node_script],
        check=True,
        capture_output=True,
        text=True,
    )

    output = completed.stdout.strip()
    assert output, completed.stderr

    result = json.loads(output)
    assert result.get("alertCount", 0) >= 1
    message = result.get("lastAlert") or ""
    assert "Privilege Leave will cover 4.00 h (0.50 d)" in message
    assert "remaining 4.00 h (0.50 d)" in message
