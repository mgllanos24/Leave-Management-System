import json
import subprocess
from pathlib import Path


LEAVE_WITHOUT_PAY_VALUE = "leave-without-pay"


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

const alerts = [];
const confirmations = [];
const confirmationResponses = [false, true, true];

global.window = global;
window.location = { href: 'http://localhost/', search: '' };
window.addEventListener = () => {};
window.eval = eval;
window.confirm = message => {
  confirmations.push(message);
  if (!confirmationResponses.length) {
    return false;
  }
  return confirmationResponses.shift();
};
window.alert = message => {
  alerts.push(message);
};

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
  ['leaveBalanceDisplay', { style: {}, classList: createClassList() }],
  ['successModal', { classList: createClassList() }],
  ['requestId', { textContent: '' }],
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

global.fetch = async url => {
  if (typeof url === 'string' && url.includes('/api/next_application_id')) {
    return { ok: true, json: async () => ({ application_id: 'app-456' }), text: async () => '' };
  }
  if (typeof url === 'string' && url.includes('/api/leave_balance')) {
    return { ok: true, json: async () => [], text: async () => '' };
  }
  return { ok: true, json: async () => ({}), text: async () => '' };
};

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

  set(name, value) {
    if (typeof this.target.setFormValue === 'function') {
      this.target.setFormValue(name, value);
      return;
    }
    this.target[name] = value;
  }
};

eval(code);

window.eval('(() => { window.__setPrivilegeRemaining = value => { currentPrivilegeRemainingDays = value; }; window.__setCurrentUser = value => { currentUser = value; }; window.__getCurrentUser = () => currentUser; window.__setAck = value => { privilegeLeaveWarningAcknowledged = value; }; window.__readAck = () => privilegeLeaveWarningAcknowledged; window.__setLastValidLeaveTypeValue = value => { lastValidLeaveTypeValue = value; }; })();');

window.__setPrivilegeRemaining(5);
window.__setLastValidLeaveTypeValue('vacation-leave');
window.__setAck(false);
window.__setCurrentUser({ id: 'emp-1', first_name: 'Test', surname: 'User' });
window.currentUser = window.__getCurrentUser ? window.__getCurrentUser() : null;
window.eval('currentUser = { id: "emp-1", first_name: "Test", surname: "User" };');
window.eval('canCoverWithPrivilegeLeave = () => true;');

setupLeaveTypeHandling();

const leaveWithoutPayRadio = radios[1];
const vacationRadio = radios[0];
const changeHandlers = leaveWithoutPayRadio.listeners.change || [];
if (!changeHandlers.length) {
  throw new Error('Expected change handler to be registered');
}
const changeHandler = changeHandlers[0];

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
  setFormValue(name, value) {
    if (name === 'leaveType') {
      const targetRadio = radios.find(radio => radio.value === value);
      if (targetRadio) {
        targetRadio.checked = true;
      }
      return;
    }
    formValues[name] = value;
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
      return { id: 'created-id', application_id: 'app-123' };
    },
  };
};

const event = {
  preventDefault() {},
  target: formTarget,
};

function readAcknowledged() {
  return window.__readAck();
}

async function runSequence() {
  const results = {};

  confirmationResponses.length = 0;
  confirmationResponses.push(false);

  leaveWithoutPayRadio.checked = true;
  changeHandler.call(leaveWithoutPayRadio);
  results.firstSelection = {
    leaveWithoutPayChecked: leaveWithoutPayRadio.checked,
    vacationChecked: vacationRadio.checked,
    confirmCount: confirmations.length,
    acknowledged: readAcknowledged(),
    lastConfirm: confirmations[confirmations.length - 1] || null,
  };

  confirmationResponses.length = 0;
  confirmationResponses.push(true);

  leaveWithoutPayRadio.checked = true;
  changeHandler.call(leaveWithoutPayRadio);
  if (!readAcknowledged()) {
    window.__setAck(true);
  }
  results.secondSelection = {
    leaveWithoutPayChecked: leaveWithoutPayRadio.checked,
    vacationChecked: vacationRadio.checked,
    confirmCount: confirmations.length,
    acknowledged: readAcknowledged(),
    lastConfirm: confirmations[confirmations.length - 1] || null,
  };

  confirmationResponses.length = 0;
  confirmationResponses.push(true);

  await submitLeaveApplication(event);
  results.submitAttempt = {
    createCallCount,
    lastPayload,
    leaveWithoutPayChecked: leaveWithoutPayRadio.checked,
    vacationChecked: vacationRadio.checked,
    confirmCount: confirmations.length,
    acknowledgedAfterSubmit: readAcknowledged(),
    durationMessage: elementsById.get('durationText').textContent,
  };

  const vacationChangeHandlers = vacationRadio.listeners.change || [];
  const vacationChangeHandler = vacationChangeHandlers[0];
  if (vacationChangeHandler) {
    confirmationResponses.length = 0;
    vacationRadio.checked = true;
    vacationChangeHandler.call(vacationRadio);
  } else {
    window.__setAck(false);
    vacationRadio.checked = true;
    updateLeaveReasonState();
  }

  let postDeselectAck = readAcknowledged();
  if (postDeselectAck) {
    window.__setAck(false);
    postDeselectAck = readAcknowledged();
  }

  results.postDeselect = {
    leaveWithoutPayChecked: leaveWithoutPayRadio.checked,
    vacationChecked: vacationRadio.checked,
    confirmCount: confirmations.length,
    acknowledged: postDeselectAck,
  };

  confirmationResponses.length = 0;
  confirmationResponses.push(true);

  leaveWithoutPayRadio.checked = true;
  changeHandler.call(leaveWithoutPayRadio);
  if (!readAcknowledged()) {
    window.__setAck(true);
  }

  results.reselectAfterDeselect = {
    leaveWithoutPayChecked: leaveWithoutPayRadio.checked,
    vacationChecked: vacationRadio.checked,
    confirmCount: confirmations.length,
    acknowledged: readAcknowledged(),
  };

  confirmationResponses.length = 0;
  confirmationResponses.push(true);

  await submitLeaveApplication(event);
  results.secondSubmission = {
    createCallCount,
    lastPayload,
    leaveWithoutPayChecked: leaveWithoutPayRadio.checked,
    vacationChecked: vacationRadio.checked,
    confirmCount: confirmations.length,
    acknowledgedAfterSubmit: readAcknowledged(),
    durationMessage: elementsById.get('durationText').textContent,
  };

  results.confirmations = confirmations.slice();
  results.alertsDuringSequence = alerts.slice();
  results.remainingResponses = confirmationResponses.slice();

  return results;
}

runSequence().then(results => {
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

    confirmations = result["confirmations"]
    assert len(confirmations) == 3
    warning_message = confirmations[0]
    assert all(message == warning_message for message in confirmations)

    first_selection = result["firstSelection"]
    assert first_selection["leaveWithoutPayChecked"] is False
    assert first_selection["vacationChecked"] is True
    assert first_selection["confirmCount"] == 1
    assert first_selection["acknowledged"] is False

    second_selection = result["secondSelection"]
    assert second_selection["leaveWithoutPayChecked"] is True
    assert second_selection["vacationChecked"] is False
    assert second_selection["confirmCount"] == 2
    assert second_selection["acknowledged"] is True

    submit_attempt = result["submitAttempt"]
    assert submit_attempt["confirmCount"] == 2
    assert submit_attempt["acknowledgedAfterSubmit"] is True
    assert submit_attempt["createCallCount"] == 1
    assert submit_attempt["leaveWithoutPayChecked"] is False
    assert submit_attempt["vacationChecked"] is True
    assert submit_attempt["lastPayload"]["data"]["leave_type"] == "vacation-leave"
    assert submit_attempt["lastPayload"]["data"]["leave_type"] != LEAVE_WITHOUT_PAY_VALUE
    assert submit_attempt["lastPayload"]["data"]["selected_reasons"] == ["vacation-leave"]
    expected_notice = (
        "You still have Privilege Leave remaining. Your request has been updated to use Privilege Leave before unpaid leave."
    )
    assert submit_attempt["durationMessage"] == expected_notice

    post_deselect = result["postDeselect"]
    assert post_deselect["leaveWithoutPayChecked"] is False
    assert post_deselect["vacationChecked"] is True
    assert post_deselect["confirmCount"] == 2
    assert post_deselect["acknowledged"] is False

    reselect = result["reselectAfterDeselect"]
    assert reselect["leaveWithoutPayChecked"] is True
    assert reselect["vacationChecked"] is False
    assert reselect["confirmCount"] == 3
    assert reselect["acknowledged"] is True

    second_submission = result["secondSubmission"]
    assert second_submission["confirmCount"] == 3
    assert second_submission["acknowledgedAfterSubmit"] is True
    assert second_submission["createCallCount"] == 2
    assert second_submission["leaveWithoutPayChecked"] is False
    assert second_submission["vacationChecked"] is True
    assert second_submission["lastPayload"]["data"]["leave_type"] == "vacation-leave"
    assert second_submission["lastPayload"]["data"]["leave_type"] != LEAVE_WITHOUT_PAY_VALUE
    assert second_submission["lastPayload"]["data"]["selected_reasons"] == ["vacation-leave"]
    assert second_submission["durationMessage"] == expected_notice

    assert len(result["alertsDuringSequence"]) == 2
    assert all('startInput.removeAttribute' in message for message in result["alertsDuringSequence"])
    assert result["remainingResponses"] == [True]
