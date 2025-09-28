# Employee Leave Management System

A comprehensive web-based leave management system designed for small to medium organizations. This system allows employees to submit leave requests and administrators to manage employees and approve/reject leave applications.

## Features

### 🏢 For Organizations
- **Dual Interface**: Separate login portals for employees and administrators
- **Leave Tracking**: Track different types of leave (Annual, Sick, Personal, etc.)
- **Holiday Management**: Configure company holidays that are excluded from leave calculations
- **Email Notifications**: Automatic email alerts to administrators for new applications
- **Data Backup**: Export and import functionality for data backup and migration

### 👤 For Employees
- **Easy Application**: Simple form to request leave with date selection
- **Half-Day Support**: Request full days, AM only, or PM only
- **Status Tracking**: View application status and history
- **Real-time Notifications**: Get notified when applications are approved or rejected
- **Balance Checking**: Automatic validation against available leave balance
- **Application ID Preview**: Retrieve the next unique application ID via `/api/next_application_id`

### 🔐 For Administrators
- **Employee Management**: Add, edit, and manage employee records
- **Application Review**: Approve or reject leave applications
- **Leave Summary**: Overview of all employee leave balances and usage
- **Holiday Configuration**: Set company-wide holidays
- **Data Management**: Backup and restore system data

## Quick Start Guide

### Step 1: Installation

1. **Download the system files** to your computer
2. **Install Python** (version 3.7 or later) from [python.org](https://python.org)
3. **Open a terminal/command prompt** in the system folder

### Step 2: Configuration

#### Email Notifications (Optional but Recommended)
1. Configure your email credentials in `services/email_service.py` or via
   environment variables.
2. Replace the default credentials:
   ```python
   SMTP_USERNAME = "your-email@gmail.com"  # Your Gmail address
   SMTP_PASSWORD = "your-app-password"     # Your Gmail App Password
   ```

#### Administrator Email

The server requires an email address for the administrator so notifications can
be delivered when employees submit leave requests. Set this via an
`ADMIN_EMAIL` environment variable. The application will read variables from a
local `.env` file if present:

```bash
# .env
ADMIN_EMAIL=admin@example.com
```

Make sure to provide a real address in production so alerts reach the
appropriate person.

### Manual Verification

#### Leave Without Pay History Display

To confirm that leave without pay records appear under **Unpaid Hours** in the
Leave History views:

1. Start the development server as described in the Quick Start Guide.
2. Create or update a leave application with the leave type set to
   `Leave-Without-Pay` (hyphenated) or `Leave without pay` (spaced). Ensure it
   spans at least one working day.
3. Refresh the **Leave History** tab (or **Admin Leave History** for admin
   users).
4. Verify that the entry shows `0` under **Paid Hours** and the full duration of
   the leave under **Unpaid Hours**.

These steps confirm the UI correctly classifies leave without pay as unpaid
even when no balance history record is associated with the application.

