# Agro-Intel Backend

The **Agro-Intel Backend** is a Flask + Socket.IO REST API built to power the Agro-Intel web platform and mobile clients. It manages **farmer** and **agriculturalist** accounts, real-time **soil sensor data**, **appointment booking** with 30-minute slots, **real-time chat**, persistent **unread message counts**, and secure **authentication** using JWT and OTP-based email verification.

It uses **MongoDB** for persistence, **bcrypt** for password hashing, **JWT** for session handling, **Socket.IO** for real-time communication, and **SMTP** (Gmail) for OTP and CSV email delivery.

---

## Table of Contents

- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Environment Variables](#environment-variables)
- [Running the Application](#running-the-application)
- [Deploying to Production](#deploying-to-production)
- [API Endpoints](#api-endpoints)
- [Socket.IO Events](#socketio-events)
- [Testing](#testing)
- [Directory Structure](#directory-structure)
- [Database Schema \\& Indexes](#database-schema--indexes)
- [MongoDB CLI Commands](#mongodb-cli-commands)
- [Contributing](#contributing)

---

## Features

- **Dual User Roles**: `farmer` and `agriculturalist` with separate collections.
- **OTP-based Email Verification** for registration, password reset, and password/profile update flows.
- **JWT Authentication** with access control based on authenticated identity.
- **IoT Sensor Data Ingestion** with validation.
- **Sensor Data CSV Download** — farmer can download the last 30 days of data as a `.csv` file.
- **Secure Sensor Data Sharing** — farmer can email the last 30 days of sensor data as CSV to an appointed agriculturalist only.
- **30-Minute Time Slot Booking** from `00:00` to `23:30`.
- **Availability Management** for agriculturalists up to 7 days in advance.
- **Appointment Booking & Cancellation** with conflict detection.
- **Real-Time Chat** via Socket.IO — unlocked only after a completed appointment between a farmer and an agriculturalist.
- **Message Edit & Delete** — users can edit or delete only their own messages, with live synchronization to the other party.
- **Chat History TTL** — chat messages are auto-deleted from MongoDB after 30 days via TTL index.
- **Unread Message Count Support** — unread counts are stored per `userId + roomId`, increment when a new message arrives, can be fetched through REST, and are cleared when the chat is opened.
- **Search & Filter Agriculturalists** by location, name, and availability.
- **Secure Password Management** with OTP verification.
- **Forgot Password Flow** for both roles.
- **Email Uniqueness** enforced across both roles.
- **UTC Timestamps** across backend responses.
- **CORS Enabled** for all origins (`*`).
- **Health Check Root Endpoint** at `/`.

---

## Prerequisites

- Python 3.8+
- MongoDB 5.0+ (local or [MongoDB Atlas](https://www.mongodb.com/cloud/atlas))
- Gmail account with App Password enabled for SMTP
- Git
- `curl` or Postman for testing

---

## Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/agro-intel-backend.git
   cd agro-intel-backend
   ```

2. **Create a virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux / Mac
   # or
   venv\Scripts\activate     # Windows
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

   Example `requirements.txt`:
   ```txt
   flask==2.3.3
   pymongo==4.8.0
   flask-cors==4.0.1
   flask-jwt-extended==4.6.0
   flask-socketio==5.3.6
   simple-websocket==1.0.0
   python-dotenv==1.0.1
   bcrypt==4.2.0
   email-validator==2.2.0
   pytz==2024.1
   gunicorn==22.0.0
   ```

   > `csv`, `io`, `logging`, `email.mime.*`, and similar modules are part of Python's standard library.

4. **Set up MongoDB**
   - Run locally with `mongod`, or
   - Use MongoDB Atlas.

5. **Initialize the database schema**
   ```bash
   python create_schema.py
   ```
   This creates the required collections and indexes, including:
   - TTL index on `chat_messages.timestamp` for 30-day message expiry
   - compound indexes for appointments lookup
   - unread count collection indexes if defined in schema init

6. **Create a `.env` file**
   ```env
   MONGO_URI=mongodb://localhost:27017/agro_intel
   JWT_SECRET_KEY=your_very_strong_secret_key_here
   FARMER_ID_PREFIX=FARM
   AGRICULTURALIST_ID_PREFIX=AGRI
   SMTP_EMAIL=your-email@gmail.com
   SMTP_PASSWORD=your-app-password
   SERVER_HOST=127.0.0.1
   SERVER_PORT=5000
   ```

---

## Environment Variables

| Variable | Description | Example |
|---|---|---|
| `MONGO_URI` | MongoDB connection string | `mongodb://localhost:27017/agro_intel` |
| `JWT_SECRET_KEY` | Secret used to sign JWT tokens | `super-secret-key` |
| `FARMER_ID_PREFIX` | Prefix for generated farmer IDs | `FARM` |
| `AGRICULTURALIST_ID_PREFIX` | Prefix for generated agriculturalist IDs | `AGRI` |
| `SMTP_EMAIL` | Gmail address used for OTP and CSV email sending | `your-email@gmail.com` |
| `SMTP_PASSWORD` | Gmail App Password | `xxxx xxxx xxxx xxxx` |
| `SERVER_HOST` | Bind host for Flask app | `127.0.0.1` |
| `SERVER_PORT` | Port for Flask app | `5000` |

---

## Running the Application

1. **Start MongoDB** if running locally
   ```bash
   mongod
   ```

2. **Run the backend**
   ```bash
   python app.py
   ```

3. **Test the root endpoint**
   ```bash
   curl http://127.0.0.1:5000/
   ```

   Expected response:
   ```txt
   Agro-Intel Server is up and Running
   ```

---

## Deploying to Production

### Gunicorn + Nginx + Supervisor

> Since the app uses **Socket.IO** with threading mode, use a worker setup compatible with long-lived connections. Avoid the default sync worker.

1. **Install system packages**
   ```bash
   sudo apt update && sudo apt upgrade -y
   sudo apt install python3 python3-pip python3-venv git nginx supervisor -y
   ```

2. **Clone and configure the project**
   ```bash
   sudo mkdir -p /var/www/agro_intel_backend
   sudo chown $USER:$USER /var/www/agro_intel_backend
   cd /var/www/agro_intel_backend
   git clone https://github.com/yourusername/agro-intel-backend.git .
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt gunicorn
   ```

3. **Add environment variables**
   ```bash
   nano .env
   chmod 600 .env
   ```

4. **Initialize schema**
   ```bash
   python create_schema.py
   ```

5. **Test Gunicorn**
   ```bash
   gunicorn --worker-class gthread --workers 1 --threads 4 --bind 0.0.0.0:5000 app:app
   ```

6. **Supervisor config**
   ```ini
   [program:agro_intel]
   directory=/var/www/agro_intel_backend
   command=/var/www/agro_intel_backend/venv/bin/gunicorn --worker-class gthread --workers 1 --threads 4 --bind 0.0.0.0:5000 app:app
   user=ubuntu
   autostart=true
   autorestart=true
   stderr_logfile=/var/log/agro_intel.err.log
   stdout_logfile=/var/log/agro_intel.out.log
   ```

7. **Nginx config**
   ```nginx
   server {
       listen 80;
       server_name your-domain.com;

       location / {
           proxy_pass http://127.0.0.1:5000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
       }

       location /socket.io/ {
           proxy_pass http://127.0.0.1:5000;
           proxy_http_version 1.1;
           proxy_set_header Upgrade $http_upgrade;
           proxy_set_header Connection "Upgrade";
           proxy_set_header Host $host;
       }
   }
   ```

8. **Enable SSL**
   ```bash
   sudo apt install certbot python3-certbot-nginx
   sudo certbot --nginx -d your-domain.com
   ```

---

## API Endpoints

All API routes are prefixed with `/api/` except the root endpoint `/`. Responses are JSON unless otherwise noted.

### Core Authentication & Profile

| # | Method | Endpoint | Purpose |
|---|---|---|---|
| 1 | POST | `/api/register-farmer` | Start farmer registration with OTP |
| 2 | POST | `/api/confirm-register-farmer` | Confirm farmer OTP |
| 3 | POST | `/api/register-agriculturalist` | Start agriculturalist registration with OTP |
| 4 | POST | `/api/confirm-register-agriculturalist` | Confirm agriculturalist OTP |
| 5 | POST | `/api/login-farmer` | Farmer login |
| 6 | POST | `/api/login-agriculturalist` | Agriculturalist login |
| 7 | GET | `/api/profile-farmer/<farmer_id>` | Get farmer profile |
| 8 | PUT | `/api/update-profile-farmer` | Update farmer profile |
| 9 | GET | `/api/profile-agriculturalist/<agri_id>` | Get agriculturalist profile |
| 10 | PUT | `/api/update-profile-agriculturalist` | Update agriculturalist profile |

### Discovery, Sensor, Availability, Appointment

| # | Method | Endpoint | Purpose |
|---|---|---|---|
| 11 | GET | `/api/find-agriculturalist` | Search agriculturalists |
| 12 | POST | `/api/send-sensor-data` | Ingest IoT sensor data |
| 13 | GET | `/api/get-sensor-data/<farmer_id>` | Fetch paginated sensor data |
| 14 | GET | `/api/get-latest-sensor-data/<farmer_id>` | Fetch latest sensor reading |
| 15 | GET | `/api/farmer-download-sensor-data/<farmer_id>` | Download 30-day CSV |
| 16 | POST | `/api/farmer-send-sensor-data/<farmer_id>` | Email sensor data CSV to agriculturalist |
| 17 | POST | `/api/agriculturalist-set-availability-slots` | Set agriculturalist slots |
| 18 | GET | `/api/farmer-get-available-slots/<agri_id>` | Get available slots |
| 19 | POST | `/api/farmer-book-slot` | Book slot |
| 20 | GET | `/api/farmer-appointments/<farmer_id>` | Farmer appointments |
| 21 | GET | `/api/agriculturalist-appointments/<agri_id>` | Agriculturalist appointments |
| 22 | POST | `/api/cancel-appointment/<appointment_id>` | Cancel appointment |
| 23 | POST | `/api/agriculturalist-availability-slots` | View own slots |

### Password & Recovery

| # | Method | Endpoint | Purpose |
|---|---|---|---|
| 24 | POST | `/api/update-password-farmer` | Start farmer password update |
| 25 | POST | `/api/confirm/update-password-farmer` | Confirm farmer password update |
| 26 | POST | `/api/update-password-agriculturalist` | Start agriculturalist password update |
| 27 | POST | `/api/confirm/update-password-agriculturalist` | Confirm agriculturalist password update |
| 28 | POST | `/api/forgot-password` | Start forgot password flow |
| 29 | POST | `/api/confirm-forgot-password` | Confirm forgot password flow |

### Chat & Unread Counts

| # | Method | Endpoint | Purpose |
|---|---|---|---|
| 30 | POST | `/api/chat/verify-access` | Verify completed appointment and return `roomId` |
| 31 | GET | `/api/chat/messages/<room_id>` | Fetch last 50 room messages |
| 32 | GET | `/api/unread-counts/<user_id>` | Fetch unread message counts for a user |
| 33 | DELETE | `/api/unread-counts/<user_id>/<room_id>` | Clear unread count for one room |

### Root

| # | Method | Endpoint | Purpose |
|---|---|---|---|
| 0 | GET | `/` | Health check |

### Sample Chat/Unread Endpoints

#### Verify Chat Access
```bash
curl -X POST http://127.0.0.1:5000/api/chat/verify-access \
-H "Content-Type: application/json" \
-H "Authorization: Bearer <JWT_TOKEN>" \
-d '{"otherUserId":"AGRI789012"}'
```

#### Get Chat Messages
```bash
curl -X GET http://127.0.0.1:5000/api/chat/messages/CHAT_FARM123456_AGRI789012 \
-H "Authorization: Bearer <JWT_TOKEN>"
```

#### Get Unread Counts
```bash
curl -X GET http://127.0.0.1:5000/api/unread-counts/FARM123456 \
-H "Authorization: Bearer <JWT_TOKEN>"
```

#### Clear Unread Count for a Room
```bash
curl -X DELETE http://127.0.0.1:5000/api/unread-counts/FARM123456/CHAT_FARM123456_AGRI789012 \
-H "Authorization: Bearer <JWT_TOKEN>"
```

---

## Socket.IO Events

The server uses **Socket.IO** with `async_mode="threading"`.

### Client → Server

#### `join_room`
```json
{ "roomId": "CHAT_FARM123456_AGRI789012", "userId": "FARM123456" }
```

#### `join_personal_room`
```json
{ "userId": "FARM123456" }
```

#### `send_message`
```json
{
  "roomId": "CHAT_FARM123456_AGRI789012",
  "senderId": "FARM123456",
  "senderRole": "farmer",
  "receiverId": "AGRI789012",
  "message": "Hello!"
}
```

#### `edit_message`
```json
{
  "roomId": "CHAT_FARM123456_AGRI789012",
  "messageId": "64f1a2b3c4d5e6f7a8b9c0d1",
  "senderId": "FARM123456",
  "newMessage": "Hello, updated!"
}
```

#### `delete_message`
```json
{
  "roomId": "CHAT_FARM123456_AGRI789012",
  "messageId": "64f1a2b3c4d5e6f7a8b9c0d1",
  "senderId": "FARM123456"
}
```

#### `leave_room`
```json
{ "roomId": "CHAT_FARM123456_AGRI789012", "userId": "FARM123456" }
```

### Server → Client

| Event | Payload | Description |
|---|---|---|
| `joined` | `{ roomId, userId }` | Confirms room join |
| `personal_room_joined` | `{ userId }` | Confirms personal notification room join |
| `receive_message` | `{ messageId, senderId, senderRole, message, timestamp }` | Broadcasts new message |
| `new_message_notification` | `{ roomId }` | Notifies receiver to refresh unread badge state |
| `message_edited` | `{ messageId, newMessage, editedAt }` | Broadcasts message edit |
| `message_deleted` | `{ messageId }` | Broadcasts message delete |
| `error` | `{ message }` | Generic event error |

---

## Testing

1. **Start the server**
   ```bash
   python app.py
   ```

2. **Suggested test flow**
   ```txt
   Register farmer → Confirm OTP → Login →
   Register agriculturalist → Confirm OTP → Login →
   Create availability → Book appointment →
   Mark appointment completed in MongoDB →
   Verify chat access → join_room → send_message →
   Check unread counts → open chat → clear unread count
   ```

3. **Test unread count flow**
   - Send a message from one user.
   - Ensure `unread_counts` gets incremented for the receiver.
   - Call `GET /api/unread-counts/<user_id>`.
   - Open chat on frontend or call the DELETE unread endpoint.
   - Confirm the unread count document is removed.

---

## Directory Structure

```bash
agro-intel-backend/
├── app.py                 # Main Flask + Socket.IO application
├── create_schema.py       # MongoDB schema and index initialization
├── requirements.txt
├── .env                   # Environment variables (not tracked)
├── venv/
└── logs/                  # Optional runtime logs
```

---

## Database Schema & Indexes

### `farmers`
```js
{
  _id: "FARM123456",
  name,
  email,
  mobileNumber,
  password,
  deviceId,
  upiId,
  cityVillage,
  district,
  state,
  isEmailVerified: true,
  createdAt,
  updatedAt
}
```
Indexes: unique `email`, unique `mobileNumber`, `deviceId`, `state`, `district`, `cityVillage`, `isEmailVerified`, `createdAt`

### `agriculturalists`
```js
{
  _id: "AGRI789012",
  name,
  email,
  mobileNumber,
  password,
  upiId,
  address,
  cityVillage,
  district,
  state,
  pincode,
  isAvailable: true,
  isEmailVerified: true,
  createdAt,
  updatedAt
}
```
Indexes: unique `email`, unique `mobileNumber`, `state`, `district`, `cityVillage`, `pincode`, `isAvailable`, `isEmailVerified`, `createdAt`

### `sensor_data`
```js
{
  farmerId,
  deviceId,
  nitrogen,
  phosphorous,
  potassium,
  soil_moisture,
  soil_ph,
  soil_temp,
  timestamp,
  createdAt
}
```
Indexes: `farmerId`, `deviceId`, `timestamp`, compound `farmerId+timestamp`, compound `farmerId+deviceId`

### `availability_slots`
```js
{
  agriculturalistId,
  date: "2025-11-05",
  slotTime: "09:30",
  slotEndTime: "10:00",
  dayOfWeek: "Wednesday",
  isBooked: false,
  bookedBy: null,
  createdAt
}
```
Unique index: `{ agriculturalistId: 1, date: 1, slotTime: 1 }`

### `appointments`
```js
{
  farmerId,
  agriculturalistId,
  slotId,
  date,
  slotTime,
  slotEndTime,
  dayOfWeek,
  status: "booked" | "cancelled" | "completed",
  cancelledBy,
  cancelledAt,
  createdAt
}
```
Indexes: `farmerId`, `agriculturalistId`, `slotId`, `status`, `date`, `createdAt`, compound `farmerId+status`, compound `agriculturalistId+status`, compound `farmerId+date`, compound `farmerId+agriculturalistId+status`

### `chat_messages`
```js
{
  roomId: "CHAT_FARM123456_AGRI789012",
  senderId: "FARM123456",
  senderRole: "farmer",
  message: "Hello Doctor!",
  edited: false,
  editedAt: null,
  timestamp: ISODate()
}
```
Indexes: compound `roomId+timestamp`, TTL index on `timestamp` with 30-day expiry

### `unread_counts`
```js
{
  userId: "FARM123456",
  roomId: "CHAT_FARM123456_AGRI789012",
  count: 3
}
```
Indexes: unique compound `{ userId: 1, roomId: 1 }`, optional `userId` index for lookup speed

### `pending_updates`
```js
{
  userId,
  type,
  email,
  createdAt
}
```
TTL: auto-deleted after 10 minutes

### `otps`
```js
{
  userId,
  email,
  createdAt
}
```
TTL: auto-deleted after 10 minutes

---

## MongoDB CLI Commands

```bash
mongosh
use agro_intel
```

```js
show collections

// View chat messages in a room
db.chat_messages.find({
  roomId: "CHAT_FARM123456_AGRI789012"
}).sort({ timestamp: 1 })

// View unread counts for a user
db.unread_counts.find({
  userId: "FARM123456"
})

// Check unread count index
db.unread_counts.getIndexes()

// Mark appointment as completed for chat testing
db.appointments.updateOne(
  { farmerId: "FARM123456", agriculturalistId: "AGRI789012" },
  { $set: { status: "completed" } }
)

// Check chat TTL index
db.chat_messages.getIndexes()
```

---

## Contributing

1. Fork the repository.
2. Create a feature branch:
   ```bash
   git checkout -b feature/your-feature
   ```
3. Commit your changes:
   ```bash
   git commit -m "Add your feature"
   ```
4. Push to the branch:
   ```bash
   git push origin feature/your-feature
   ```
5. Open a pull request.

---

**Project maintained with love for farmers and agricultural experts.**