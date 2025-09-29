import json
import subprocess
from pathlib import Path


def test_privilege_leave_warning_confirm_paths():
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "script.js"

    node_script = """
const fs = require('fs');
const code = fs.readFileSync(__SCRIPT_PATH__, 'utf8');

const originalLog = console.log;
console.log = () => {};

function createClassList() {
  return {
    add() {},
    remove() {},
  };
}

class RadioInput {
  constructor(value) {
    this.value = value;
    this.name = 'leaveType';
    this.type = 'radio';
    this._checked = false;
    this._peers = null;
    this.dataset = {};
    this.style = {};
    this.classList = createClassList();
    this.listeners = {};
  }

  set checked(value) {
    const isChecked = Boolean(value);
    if (this._checked === isChecked) {
      this._checked = isChecked;
      return;
    }
    this._checked = isChecked;
    if (isChecked && Array.isArray(this._peers)) {
      this._peers.forEach(peer => {
        if (peer !== this) {
          peer._checked = false;
        }
      });
    }
  }

  get checked() {
    return this._checked;
  }

  setPeers(peers) {
    this._peers = peers;
  }

  addEventListener(event, handler) {
    if (!this.listeners[event]) {
      this.listeners[event] = [];
    }
    this.listeners[event].push(handler);
  }
}

global.window = global;
window.location = { href: 'http://localhost/', search: '' };
window.addEventListener = () => {};
window.eval = eval;
window.confirm = () => false;
window.alert = () => {};

const radios = [
  new RadioInput('vacation-leave'),
  new RadioInput('leave-without-pay'),
];
radios.forEach(radio => radio.setPeers(radios));
radios[0].checked = true;

const elementsById = new Map([
  ['reason', { disabled: false }],
  ['reasonNote', { textContent: '' }],
  ['durationText', { textContent: '' }],
  ['startDate', { value: '2024-01-01' }],
  ['endDate', { value: '2024-01-01' }],
  ['startTime', { value: '07:30', dataset: {}, classList: createClassList() }],
  ['endTime', { value: '14:30', dataset: {}, classList: createClassList() }],
  ['loadingOverlay', { classList: createClassList() }],
]);

global.document = {
  getElementById(id) {
    if (elementsById.has(id)) {
      return elementsById.get(id);
    }
    const created = { dataset: {}, classList: createClassList(), style: {} };
    elementsById.set(id, created);
    return created;
  },
  querySelectorAll(selector) {
    if (selector === 'input[name="leaveType"]') {
      return radios;
    }
    return [];
  },
  querySelector(selector) {
    if (selector === 'input[name="leaveType"]:checked') {
      return radios.find(radio => radio.checked) || null;
    }
    return null;
  },
  addEventListener: () => {},
  createElement: tag => ({ tagName: tag, classList: createClassList(), dataset: {}, style: {} }),
};

global.navigator = { userAgent: 'node' };
global.sessionStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
global.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };

global.fetch = async () => ({ ok: true, json: async () => ({}), text: async () => '' });

global.FormData = class {
  constructor(target) {
    this.target = target;
  }

  get(name) {
    if (typeof this.target.getFormValue === 'function') {
      return this.target.getFormValue(name);
    }
    return this.target[name] ?? null;
  }
};

eval(code);

window.eval('(() => { currentPrivilegeRemainingDays = 5; })();');
window.eval('(() => { lastValidLeaveTypeValue = "vacation-leave"; })();');
window.eval('canCoverWithPrivilegeLeave = () => true;');

setupLeaveTypeHandling();

const leaveWithoutPayRadio = radios[1];
const vacationRadio = radios[0];
const changeHandlers = leaveWithoutPayRadio.listeners.change || [];
if (!changeHandlers.length) {
  throw new Error('Expected change handler to be registered');
}
const changeHandler = changeHandlers[0];
const alerts = [];
window.alert = message => {
  alerts.push(message);
};

window.eval('(() => { currentUser = { id: "emp-1", first_name: "Test", surname: "User" }; })();');

const results = {};
let warningMessage = null;

leaveWithoutPayRadio.checked = true;
changeHandler.call(leaveWithoutPayRadio);
warningMessage = alerts[alerts.length - 1] || null;
results.changeSelection = {
  leaveWithoutPayChecked: leaveWithoutPayRadio.checked,
  vacationChecked: vacationRadio.checked,
  alertCount: alerts.length,
  lastAlert: alerts[alerts.length - 1] || null,
};

const formValues = {
  startDate: '2024-01-01',
  endDate: '2024-01-01',
  startTime: '07:30',
  endTime: '14:30',
  reason: 'Testing',
};

const formTarget = {
  getFormValue(name) {
    if (name === 'leaveType') {
      const selected = radios.find(radio => radio.checked);
      return selected ? selected.value : null;
    }
    return Object.prototype.hasOwnProperty.call(formValues, name) ? formValues[name] : null;
  },
  reset() {},
};

let createCallCount = 0;
let lastPayload = null;

room.collection = function(name) {
  return {
    create: async data => {
      createCallCount += 1;
      lastPayload = { name, data };
      return { id: 'created-id' };
    },
  };
};

const event = {
  preventDefault() {},
  target: formTarget,
};

async function runSubmissionSequence() {
  window.eval('(() => { lastValidLeaveTypeValue = "vacation-leave"; privilegeLeaveWarningAcknowledged = false; })();');

  leaveWithoutPayRadio.checked = true;
  updateLeaveReasonState();

  await submitLeaveApplication(event);

  results.submitAttempt = {
    createCallCount,
    lastPayload,
    leaveWithoutPayChecked: leaveWithoutPayRadio.checked,
    vacationChecked: vacationRadio.checked,
    alertCount: alerts.length,
    lastAlert: alerts[alerts.length - 1] || null,
    durationMessage: elementsById.get('durationText').textContent,
  };

  results.alertMessages = alerts.slice();
  results.warningMessage = warningMessage;
}

runSubmissionSequence().then(() => {
  console.log = originalLog;
  console.log(JSON.stringify(results));
}).catch(error => {
  console.log = originalLog;
  console.error(error);
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

    warning_message = result["warningMessage"]

    change_selection = result["changeSelection"]
    assert change_selection["leaveWithoutPayChecked"] is False
    assert change_selection["vacationChecked"] is True
    assert change_selection["alertCount"] == 1
    assert change_selection["lastAlert"] == warning_message

    submit_attempt = result["submitAttempt"]
    assert submit_attempt["createCallCount"] == 0
    assert submit_attempt["lastPayload"] is None
    assert submit_attempt["leaveWithoutPayChecked"] is False
    assert submit_attempt["vacationChecked"] is True
    assert submit_attempt["alertCount"] == 2
    assert submit_attempt["lastAlert"] == warning_message
    assert submit_attempt["durationMessage"] == warning_message

    assert result["alertMessages"] == [warning_message, warning_message]
