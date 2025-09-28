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
  constructor() {}
  append() {}
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
    total_hours: 56,
    start_date: '2024-03-01',
    end_date: '2024-03-07',
    start_time: '08:00',
    end_time: '17:00',
    leave_type: 'Leave Without Pay',
    status: 'Approved',
  },
];

const balanceHistory = [
  {
    employee_id: 'emp-1',
    application_id: '101',
    change_type: 'DEDUCTION',
    balance_type: 'PRIVILEGE',
    change_amount: 5,
    previous_balance: 5,
    new_balance: 0,
  },
  {
    employee_id: 'emp-1',
    application_id: '101',
    change_type: 'UNPAID',
    balance_type: 'PRIVILEGE',
    change_amount: 2,
    previous_balance: 0,
    new_balance: 0,
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
    paidCell: cells[5] || null,
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
    assert result.get("paidCell") == "40.00 h"
    assert result.get("unpaidCell") == "16.00 h"
