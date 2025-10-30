# Agro-Intel Backend

The **Agro-Intel Backend** is a Flask-based REST API designed to power the Agro-Intel web interface and mobile app, enabling seamless management of **farmer** and **agriculturalist** accounts, real-time **soil sensor data**, **appointment booking** with 30-minute time slots, and secure **authentication** using JWT and OTP-based email verification. It uses **MongoDB** for data storage, **bcrypt** for password hashing, **JWT** for session management, and **SMTP** (Gmail) for sending OTPs.

Key features include:
- Registration/login for **farmers** and **agriculturalists** with OTP verification.
- IoT sensor data ingestion with validation.
- Agriculturalist availability management (up to 7 days in advance).
- Appointment booking and cancellation with conflict detection.
- Profile management, password reset, and secure updates.
- Email uniqueness enforced across both roles.
- All timestamps are in **UTC** (convert to IST in frontend if needed).
- CORS enabled for all origins (`*`).

---

## Table of Contents
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Environment Variables](#environment-variables)
- [Running the Application](#running-the-application)
- [Deploying to Production](#deploying-to-production)
- [API Endpoints](#api-endpoints)
- [Testing](#testing)
- [Directory Structure](#directory-structure)
- [Contributing](#contributing)
- [Database Schema & Indexes](#database-schema--indexes)
- [MongoDB CLI Commands](#mongodb-cli-commands)

---

## Features

- **Dual User Roles**: `farmer` and `agriculturalist` with separate collections.
- **OTP-based Email Verification** for registration, password reset, and profile updates.
- **JWT Authentication** with role-based access control (`userType` claim).
- **IoT Sensor Data Ingestion** with range validation and TTL (optional).
- **30-Minute Time Slot Booking** (00:00 to 23:30).
- **Availability Management** for agriculturalists (up to 7 days in advance).
- **Appointment Booking & Cancellation** with conflict prevention.
- **Search & Filter Agriculturalists** by location, name, availability.
- **Secure Password Management** (old → OTP → new).
- **Email Uniqueness** enforced across both roles.
- **CORS enabled** for all origins (`*`).
- **Root endpoint (`/`)** returns `"Agro-Intel Server is up and Running"`.

---

## Prerequisites

- Python 3.8+
- MongoDB 5.0+ (local or [MongoDB Atlas](https://www.mongodb.com/cloud/atlas))
- Gmail account (for SMTP) with **App Password** (if 2FA enabled)
- Git
- `curl` or Postman for testing

---

## Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/yourusername/agro-intel-backend.git
   cd agro-intel-backend
   ```

2. **Create virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/Mac
   # or
   venv\Scripts\activate     # Windows
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

   Ensure `requirements.txt` includes:
   ```txt
   flask==2.3.3
   pymongo==4.8.0
   flask-cors==4.0.1
   flask-jwt-extended==4.6.0
   python-dotenv==1.0.1
   bcrypt==4.2.0
   email-validator==2.2.0
   pytz==2024.1
   gunicorn==22.0.0
   ```

4. **Set up MongoDB**:
   - Run locally: `mongod`
   - Or use [MongoDB Atlas](https://cloud.mongodb.com)

5. **Create `.env` file**:
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

| Variable | Description |
|--------|-----------|
| `MONGO_URI` | MongoDB connection string |
| `JWT_SECRET_KEY` | Secret for JWT signing (strong random string) |
| `FARMER_ID_PREFIX` | Prefix for farmer IDs (`FARM`) |
| `AGRICULTURALIST_ID_PREFIX` | Prefix for agriculturalist IDs (`AGRI`) |
| `SMTP_EMAIL` | Gmail address for sending OTPs |
| `SMTP_PASSWORD` | Gmail **App Password** |
| `SERVER_HOST` | `127.0.0.1` (dev), `0.0.0.0` (prod) |
| `SERVER_PORT` | Default `5000` |

---

## Running the Application

1. **Start MongoDB** (if local):
   ```bash
   mongod
   ```

2. **Run the app**:
   ```bash
   python app.py
   ```

3. **Test root endpoint**:
   ```bash
   curl http://127.0.0.1:5000/
   ```
   **Expected**: `"Agro-Intel Server is up and Running"`

---

## Deploying to Production

### Using Gunicorn + Nginx + Supervisor (Ubuntu)

1. **Update system**:
   ```bash
   sudo apt update && sudo apt upgrade -y
   ```

2. **Install dependencies**:
   ```bash
   sudo apt install python3 python3-pip python3-venv git nginx supervisor -y
   ```

3. **Clone & setup**:
   ```bash
   sudo mkdir -p /var/www/agro_intel_backend
   sudo chown $USER:$USER /var/www/agro_intel_backend
   cd /var/www/agro_intel_backend
   git clone https://github.com/yourusername/agro-intel-backend.git .
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt gunicorn
   ```

4. **Copy `.env`** and secure it:
   ```bash
   nano .env
   chmod 600 .env
   ```

5. **Test Gunicorn**:
   ```bash
   gunicorn --workers 3 --bind 0.0.0.0:5000 app:app
   ```

6. **Supervisor config**:
   ```bash
   sudo nano /etc/supervisor/conf.d/agro_intel.conf
   ```
   ```ini
   [program:agro_intel]
   directory=/var/www/agro_intel_backend
   command=/var/www/agro_intel_backend/venv/bin/gunicorn --workers 3 --bind 0.0.0.0:5000 app:app
   user=ubuntu
   autostart=true
   autorestart=true
   stderr_logfile=/var/log/agro_intel.err.log
   stdout_logfile=/var/log/agro_intel.out.log
   ```

7. **Nginx config**:
   ```bash
   sudo nano /etc/nginx/sites-available/agro_intel
   ```
   ```nginx
   server {
       listen 80;
       server_name your-domain.com;

       location / {
           proxy_pass http://127.0.0.1:5000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
       }
   }
   ```
   ```bash
   sudo ln -s /etc/nginx/sites-available/agro_intel /etc/nginx/sites-enabled/
   sudo nginx -t && sudo systemctl restart nginx
   ```

8. **Enable SSL (Let’s Encrypt)**:
   ```bash
   sudo apt install certbot python3-certbot-nginx
   sudo certbot --nginx -d your-domain.com
   ```

---

## API Endpoints

All endpoints are prefixed with `/api/`, except the root endpoint (`/`). Responses are JSON. Below are the 26 endpoints with `curl` commands for testing. Replace `<JWT_TOKEN>` with a valid token from the login endpoint, `<FARMER_ID>` with a valid farmer ID (e.g., `FARM123456`), and `<AGRI_ID>` with a valid agriculturalist ID (e.g., `AGRI789012`). Use your real email for OTP-based endpoints. Timestamps in responses are in UTC.

### 0. Root Endpoint
- **Path**: `/`
- **Method**: GET
- **Description**: Checks if the server is running.
- **curl Command**:
  ```bash
  curl http://127.0.0.1:5000/
  ```
- **Response**:
  - Success (200): `"Agro-Intel Server is up and Running"`

---

### 1. Register Farmer
- **Path**: `/register-farmer`
- **Method**: POST
- **Description**: Initiates farmer registration, sending an OTP to the provided email. Mandatory fields: `name`, `email`, `mobileNumber`, `password`, `cityVillage`, `district`, `state`, `deviceId`, `upiId`. Validates `deviceId` and `upiId` as non-empty strings. Ensures email and mobile uniqueness across `farmers` and `agriculturalists` collections.
- **curl Command**:
  ```bash
  curl -X POST http://127.0.0.1:5000/api/register-farmer \
  -H "Content-Type: application/json" \
  -d '{"name":"Ram Singh","email":"ram@example.com","mobileNumber":"9876543210","password":"secure123","cityVillage":"Anandpur","district":"Patiala","state":"Punjab","deviceId":"SOIL123","upiId":"ram@upi"}'
  ```
- **Response**:
  - Success (200): `{"message": "OTP sent to email for registration verification", "farmerId": "FARM123456"}`
  - Error (400, 409): `{"error": "Missing mandatory fields"}`, `{"error": "Email already exists"}`

---

### 2. Confirm Farmer Registration
- **Path**: `/confirm-register-farmer`
- **Method**: POST
- **Description**: Verifies the OTP to complete farmer registration.
- **curl Command**:
  ```bash
  curl -X POST http://127.0.0.1:5000/api/confirm-register-farmer \
  -H "Content-Type: application/json" \
  -d '{"farmerId":"FARM123456","otp":"123456"}'
  ```
- **Response**:
  - Success (201): `{"message": "Farmer Registration Successful", "farmerId": "FARM123456"}`
  - Error (400, 401, 404): `{"error": "Invalid OTP"}`, `{"error": "Pending registration not found or expired"}`

---

### 3. Register Agriculturalist
- **Path**: `/register-agriculturalist`
- **Method**: POST
- **Description**: Initiates agriculturalist registration, sending an OTP to the provided email. Mandatory fields: `name`, `email`, `mobileNumber`, `password`, `address`, `cityVillage`, `district`, `state`, `pincode`, `upiId`. Generates `agriculturalistId` as `AGRIxxxxxx`. Ensures email and mobile uniqueness across both collections.
- **curl Command**:
  ```bash
  curl -X POST http://127.0.0.1:5000/api/register-agriculturalist \
  -H "Content-Type: application/json" \
  -d '{"name":"Dr. Sharma","email":"sharma@agro.com","mobileNumber":"9123456789","password":"expert123","address":"123 Green St","cityVillage":"Hisar","district":"Hisar","state":"Haryana","pincode":"125001","upiId":"sharma@paytm"}'
  ```
- **Response**:
  - Success (200): `{"message": "OTP sent to email for registration verification", "agriculturalistId": "AGRI789012"}`
  - Error (400, 409): `{"error": "Missing mandatory fields"}`, `{"error": "Email already exists"}`

---

### 4. Confirm Agriculturalist Registration
- **Path**: `/confirm-register-agriculturalist`
- **Method**: POST
- **Description**: Verifies the OTP to complete agriculturalist registration.
- **curl Command**:
  ```bash
  curl -X POST http://127.0.0.1:5000/api/confirm-register-agriculturalist \
  -H "Content-Type: application/json" \
  -d '{"agriculturalistId":"AGRI789012","otp":"123456"}'
  ```
- **Response**:
  - Success (201): `{"message": "Agriculturalist Registration Successful", "agriculturalistId": "AGRI789012"}`
  - Error (400, 401, 404): `{"error": "Invalid OTP"}`, `{"error": "Pending registration not found or expired"}`

---

### 5. Farmer Login
- **Path**: `/login-farmer`
- **Method**: POST
- **Description**: Authenticates a farmer and returns a JWT token.
- **curl Command**:
  ```bash
  curl -X POST http://127.0.0.1:5000/api/login-farmer \
  -H "Content-Type: application/json" \
  -d '{"email":"ram@example.com","password":"secure123"}'
  ```
- **Response**:
  - Success (200): `{"message": "Farmer login successful", "farmerId": "FARM123456", "name": "Ram Singh", "token": "eyJ..."}`
  - Error (400, 401, 403): `{"error": "Invalid email or password"}`, `{"error": "Email not verified"}`

---

### 6. Agriculturalist Login
- **Path**: `/login-agriculturalist`
- **Method**: POST
- **Description**: Authenticates an agriculturalist and returns a JWT token.
- **curl Command**:
  ```bash
  curl -X POST http://127.0.0.1:5000/api/login-agriculturalist \
  -H "Content-Type: application/json" \
  -d '{"email":"sharma@agro.com","password":"expert123"}'
  ```
- **Response**:
  - Success (200): `{"message": "Agriculturalist login successful", "agriculturalistId": "AGRI789012", "token": "eyJ..."}`
  - Error (400, 401, 403): `{"error": "Invalid email or password"}`, `{"error": "Email not verified"}`

---

### 7. Get Farmer Profile
- **Path**: `/profile-farmer/<farmer_id>`
- **Method**: GET
- **Description**: Retrieves farmer profile. Requires farmer authentication (own profile only).
- **Headers**: `Authorization: Bearer <JWT_TOKEN>`
- **curl Command**:
  ```bash
  curl -X GET http://127.0.0.1:5000/api/profile-farmer/FARM123456 \
  -H "Authorization: Bearer <JWT_TOKEN>"
  ```
- **Response**:
  - Success (200):
    ```json
    {
      "message": "Farmer profile retrieved successfully",
      "profile": {
        "farmerId": "FARM123456",
        "name": "Ram Singh",
        "email": "ram@example.com",
        "mobileNumber": "9876543210",
        "cityVillage": "Anandpur",
        "district": "Patiala",
        "state": "Punjab",
        "deviceId": "SOIL123",
        "upiId": "ram@upi",
        "isEmailVerified": true,
        "createdAt": "2025-07-02T06:58:00.123Z",
        "updatedAt": "2025-07-02T06:58:00.123Z"
      }
    }
    ```
  - Error (403, 404): `{"error": "Unauthorized access"}`, `{"error": "User not found"}`

---

### 8. Update Farmer Profile
- **Path**: `/update-profile-farmer`
- **Method**: PUT
- **Description**: Updates farmer profile (except password). Updatable fields: `name`, `mobileNumber`, `cityVillage`, `district`, `state`, `upiId`. Requires farmer authentication.
- **Headers**: `Authorization: Bearer <JWT_TOKEN>`
- **curl Command**:
  ```bash
  curl -X PUT http://127.0.0.1:5000/api/update-profile-farmer \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <JWT_TOKEN>" \
  -d '{"name":"Ram Kumar","mobileNumber":"9876543211"}'
  ```
- **Response**:
  - Success (200): `{"message": "Farmer profile updated successfully", "farmerId": "FARM123456", "updatedFields": ["name", "mobileNumber"]}`
  - Error (400, 404): `{"error": "No valid fields provided for update"}`, `{"error": "Farmer not found"}`

---

### 9. Get Agriculturalist Profile
- **Path**: `/profile-agriculturalist/<agri_id>`
- **Method**: GET
- **Description**: Retrieves agriculturalist profile. Requires agriculturalist authentication (own profile only).
- **Headers**: `Authorization: Bearer <JWT_TOKEN>`
- **curl Command**:
  ```bash
  curl -X GET http://127.0.0.1:5000/api/profile-agriculturalist/AGRI789012 \
  -H "Authorization: Bearer <JWT_TOKEN>"
  ```
- **Response**:
  - Success (200): Similar structure with `address`, `pincode`, `isAvailable`
  - Error (403, 404): `{"error": "Unauthorized access"}`, `{"error": "User not found"}`

---

### 10. Update Agriculturalist Profile
- **Path**: `/update-profile-agriculturalist`
- **Method**: PUT
- **Description**: Updates agriculturalist profile (except password). Updatable fields: `name`, `mobileNumber`, `address`, `cityVillage`, `district`, `state`, `pincode`, `upiId`.
- **Headers**: `Authorization: Bearer <JWT_TOKEN>`
- **curl Command**:
  ```bash
  curl -X PUT http://127.0.0.1:5000/api/update-profile-agriculturalist \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <JWT_TOKEN>" \
  -d '{"name":"Dr. A. Sharma","pincode":"125002"}'
  ```
- **Response**:
  - Success (200): `{"message": "Agriculturalist profile updated successfully", "agriculturalistId": "AGRI789012", "updatedFields": ["name", "pincode"]}`

---

### 11. Find Agriculturalists
- **Path**: `/find-agriculturalist`
- **Method**: GET
- **Description**: Allows logged-in users to search and filter agriculturalists by name, state, district, availability. Supports pagination. Requires user authentication.
- **Headers**: `Authorization: Bearer <JWT_TOKEN>`
- **Query Parameters** (optional):
  - `state`, `district`, `isAvailable` (true/false), `search` (name/email), `page`, `limit`
- **curl Command**:
  ```bash
  curl -X GET "http://127.0.0.1:5000/api/find-agriculturalist?state=Haryana&district=Hisar&isAvailable=true&search=sharma&page=1&limit=20" \
  -H "Authorization: Bearer <JWT_TOKEN>"
  ```
- **Response**:
  - Success (200): Returns `totalCount`, `page`, `limit`, `agriculturalists` list with `agriculturalistId`, `name`, `email`, `mobileNumber`, `address`, `cityVillage`, `district`, `state`, `pincode`, `upiId`, `isAvailable`, `createdAt`

---

### 12. Send Sensor Data
- **Path**: `/send-sensor-data`
- **Method**: POST
- **Description**: Records soil sensor data from a device. Validates `deviceId` and sensor ranges.
- **curl Command**:
  ```bash
  curl -X POST http://127.0.0.1:5000/api/send-sensor-data \
  -H "Content-Type: application/json" \
  -d '{"device_id":"SOIL123","nitrogen":45.5,"phosphorous":20.1,"potassium":35.8,"soil_moisture":65.2,"soil_ph":6.8,"soil_temp":28.3}'
  ```
- **Response**:
  - Success (201): `{"message": "Sensor data received and stored successfully", "sensorDataId": "...", "farmerId": "FARM123456", "timestamp": "2025-07-02T06:58:00.123Z"}`
  - Error (400, 404): `{"error": "Device ID not found"}`, `{"error": "Nitrogen value out of range (0-300)"}`

---

### 13. Get Sensor Data (Farmer)
- **Path**: `/get-sensor-data/<farmer_id>`
- **Method**: GET
- **Description**: Retrieves sensor data for a farmer, accessible by the farmer themselves. Supports pagination.
- **Headers**: `Authorization: Bearer <JWT_TOKEN>`
- **curl Command**:
  ```bash
  curl -X GET "http://127.0.0.1:5000/api/get-sensor-data/FARM123456?page=1&limit=50" \
  -H "Authorization: Bearer <JWT_TOKEN>"
  ```
- **Response**:
  - Success (200): Returns `totalCount`, `page`, `limit`, `sensorData` list with `sensorDataId`, `deviceId`, `nitrogen`, `phosphorous`, `potassium`, `soil_moisture`, `soil_ph`, `soil_temp`, `timestamp`

---

### 14. Get Latest Sensor Data
- **Path**: `/get-latest-sensor-data/<farmer_id>`
- **Method**: GET
- **Description**: Retrieves the most recent sensor record for a farmer. Requires farmer authentication.
- **Headers**: `Authorization: Bearer <JWT_TOKEN>`
- **curl Command**:
  ```bash
  curl -X GET http://127.0.0.1:5000/api/get-latest-sensor-data/FARM123456 \
  -H "Authorization: Bearer <JWT_TOKEN>"
  ```
- **Response**:
  - Success (200): Returns latest `sensorData` object
  - Error (404): `{"error": "No sensor data found"}`

---

### 15. Set Availability Slots (Agriculturalist)
- **Path**: `/agriculturalist-set-availability-slots`
- **Method**: POST
- **Description**: Allows a logged-in agriculturalist to set availability slots for a specific date (up to 7 days in advance). Slots must be in 30-minute intervals (00:00 to 23:30).
- **Headers**: `Authorization: Bearer <JWT_TOKEN>`
- **curl Command**:
  ```bash
  curl -X POST http://127.0.0.1:5000/api/agriculturalist-set-availability-slots \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <JWT_TOKEN>" \
  -d '{"agriculturalistId":"AGRI789012","date":"2025-11-05","slots":["09:00","09:30","10:00"]}'
  ```
- **Response**:
  - Success (201): `{"message": "Availability slots set successfully", "agriculturalistId": "AGRI789012", "date": "2025-11-05", "slotsAdded": 3, "totalSlots": 3}`
  - Error (400, 403): `{"error": "Cannot set availability for past dates"}`, `{"error": "Invalid slot time"}`

---

### 16. Get Available Slots (Farmer)
- **Path**: `/farmer-get-available-slots/<agri_id>`
- **Method**: GET
- **Description**: Retrieves available slots for an agriculturalist on a specific date. Requires user authentication.
- **Headers**: `Authorization: Bearer <JWT_TOKEN>`
- **curl Command**:
  ```bash
  curl -X GET "http://127.0.0.1:5000/api/farmer-get-available-slots/AGRI789012?date=2025-11-05" \
  -H "Authorization: Bearer <JWT_TOKEN>"
  ```
- **Response**:
  - Success (200): Returns `agriculturalistName`, `availableSlots` list with `slotId`, `slotTime`, `slotEndTime`, `dayOfWeek`

---

### 17. Book Slot (Farmer)
- **Path**: `/farmer-book-slot`
- **Method**: POST
- **Description**: Allows a logged-in farmer to book a slot with an agriculturalist. Prevents double-booking.
- **Headers**: `Authorization: Bearer <JWT_TOKEN>`
- **curl Command**:
  ```bash
  curl -X POST http://127.0.0.1:5000/api/farmer-book-slot \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <JWT_TOKEN>" \
  -d '{"agriculturalistId":"AGRI789012","date":"2025-11-05","slotTime":"09:30"}'
  ```
- **Response**:
  - Success (201): `{"message": "Slot booked successfully", "appointmentId": "...", "agriculturalistName": "Dr. Sharma", "slotTime": "09:30", "slotEndTime": "10:00"}`
  - Error (409): `{"error": "This slot is already booked"}`

---

### 18. Get Farmer Appointments
- **Path**: `/farmer-appointments/<farmer_id>`
- **Method**: GET
- **Description**: Retrieves all appointments for a farmer. Optional `status` filter.
- **Headers**: `Authorization: Bearer <JWT_TOKEN>`
- **curl Command**:
  ```bash
  curl -X GET "http://127.0.0.1:5000/api/farmer-appointments/FARM123456?status=booked" \
  -H "Authorization: Bearer <JWT_TOKEN>"
  ```
- **Response**:
  - Success (200): Returns `appointments` list with `appointmentId`, `agriculturalistName`, `date`, `slotTime`, `status`

---

### 19. Get Agriculturalist Appointments
- **Path**: `/agriculturalist-appointments/<agri_id>`
- **Method**: GET
- **Description**: Retrieves all appointments for an agriculturalist.
- **Headers**: `Authorization: Bearer <JWT_TOKEN>`
- **curl Command**:
  ```bash
  curl -X GET http://127.0.0.1:5000/api/agriculturalist-appointments/AGRI789012 \
  -H "Authorization: Bearer <JWT_TOKEN>"
  ```
- **Response**:
  - Success (200): Returns `appointments` list with `farmerName`, `farmerMobile`

---

### 20. Cancel Appointment
- **Path**: `/cancel-appointment/<appointment_id>`
- **Method**: POST
- **Description**: Cancels an appointment (farmer or agriculturalist). Frees the slot.
- **Headers**: `Authorization: Bearer <JWT_TOKEN>`
- **curl Command**:
  ```bash
  curl -X POST http://127.0.0.1:5000/api/cancel-appointment/appointment123 \
  -H "Authorization: Bearer <JWT_TOKEN>"
  ```
- **Response**:
  - Success (200): `{"message": "Appointment cancelled successfully", "appointmentId": "appointment123"}`

---

### 21. View Own Slots (Agriculturalist)
- **Path**: `/agriculturalist-availability-slots`
- **Method**: POST
- **Description**: Retrieves all availability slots for the agriculturalist, grouped by date.
- **Headers**: `Authorization: Bearer <JWT_TOKEN>`
- **curl Command**:
  ```bash
  curl -X POST http://127.0.0.1:5000/api/agriculturalist-availability-slots \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <JWT_TOKEN>" \
  -d '{"agriculturalistId":"AGRI789012","date":"2025-11-05"}'
  ```
- **Response**:
  - Success (200): Returns `slotsByDate` with `slotId`, `slotTime`, `isBooked`, `bookedBy`

---

### 22. Update Farmer Password (Initiate)
- **Path**: `/update-password-farmer`
- **Method**: POST
- **Description**: Initiates password change for farmer, sending OTP after verifying old password.
- **Headers**: `Authorization: Bearer <JWT_TOKEN>`
- **curl Command**:
  ```bash
  curl -X POST http://127.0.0.1:5000/api/update-password-farmer \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <JWT_TOKEN>" \
  -d '{"oldPassword":"secure123","newPassword":"newpass456"}'
  ```
- **Response**:
  - Success (200): `{"message": "OTP sent to your email for password verification", "farmerId": "FARM123456"}`

---

### 23. Confirm Farmer Password Update
- **Path**: `/confirm/update-password-farmer`
- **Method**: POST
- **Description**: Verifies OTP to complete farmer password change.
- **Headers**: `Authorization: Bearer <JWT_TOKEN>`
- **curl Command**:
  ```bash
  curl -X POST http://127.0.0.1:5000/api/confirm/update-password-farmer \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <JWT_TOKEN>" \
  -d '{"otp":"123456"}'
  ```
- **Response**:
  - Success (200): `{"message": "Password changed successfully", "farmerId": "FARM123456"}`

---

### 24. Update Agriculturalist Password (Initiate)
- **Path**: `/update-password-agriculturalist`
- **Method**: POST
- **Description**: Initiates password change for agriculturalist.
- **Headers**: `Authorization: Bearer <JWT_TOKEN>`
- **curl Command**:
  ```bash
  curl -X POST http://127.0.0.1:5000/api/update-password-agriculturalist \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <JWT_TOKEN>" \
  -d '{"oldPassword":"expert123","newPassword":"newexpert456"}'
  ```

---

### 25. Confirm Agriculturalist Password Update
- **Path**: `/confirm/update-password-agriculturalist`
- **Method**: POST
- **Description**: Verifies OTP to complete agriculturalist password change.
- **Headers**: `Authorization: Bearer <JWT_TOKEN>`
- **curl Command**:
  ```bash
  curl -X POST http://127.0.0.1:5000/api/confirm/update-password-agriculturalist \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <JWT_TOKEN>" \
  -d '{"otp":"123456"}'
  ```

---

### 26. Forgot Password (Both Roles)
- **Path**: `/forgot-password`
- **Method**: POST
- **Description**: Initiates password reset for a user or agriculturalist, sending an OTP to the email. Checks email in both collections. Returns `userId` and `userType`.
- **curl Command**:
  ```bash
  curl -X POST http://127.0.0.1:5000/api/forgot-password \
  -H "Content-Type: application/json" \
  -d '{"email":"ram@example.com","newPassword":"newpass456"}'
  ```
- **Response**:
  - Success (200): `{"message": "OTP sent successfully", "userId": "FARM123456", "userType": "farmer"}`
  - Error (404): `{"error": "User not found"}`

---

### 27. Confirm Forgot Password
- **Path**: `/confirm-forgot-password`
- **Method**: POST
- **Description**: Verifies the OTP to complete password reset.
- **curl Command**:
  ```bash
  curl -X POST http://127.0.0.1:5000/api/confirm-forgot-password \
  -H "Content-Type: application/json" \
  -d '{"userId":"FARM123456","otp":"123456"}'
  ```
- **Response**:
  - Success (200): `{"message": "Password changed successfully", "userId": "FARM123456", "userType": "farmer"}`

---

## Testing

1. **Start the server**:
   ```bash
   python app.py
   ```

2. **Test with curl**:
   Use the `curl` commands provided above. Example workflow:
   - **Register a farmer** → Confirm OTP → Login → Send sensor data → Book appointment

3. **Test invalid inputs**:
   ```bash
   # Invalid deviceId (non-string)
   curl -X POST http://127.0.0.1:5000/api/register-farmer -d '{"deviceId":[]}'
   # Expected: {"error": "deviceId must be a non-empty string"}
   ```

---

## Directory Structure

```
agro-intel-backend/
├── app.py                    # Main Flask application
├── requirements.txt
├── .env                      # Environment variables (not tracked)
├── venv/
└── logs/                     # (optional)
```

---

## Contributing

Contributions are welcome! Please:
1. Fork the repository.
2. Create a feature branch (`git checkout -b feature/new-feature`).
3. Commit changes (`git commit -m "Add new feature"`).
4. Push to the branch (`git push origin feature/new-feature`).
5. Open a pull request.

---

## Database Schema & Indexes

### `farmers`
```js
{
  _id: "FARM123456",
  name, email, mobileNumber, password, deviceId, upiId,
  cityVillage, district, state,
  isEmailVerified: true,
  createdAt, updatedAt
}
```

### `agriculturalists`
```js
{
  _id: "AGRI789012",
  name, email, mobileNumber, password, upiId,
  address, cityVillage, district, state, pincode,
  isAvailable: true,
  isEmailVerified: true,
  createdAt, updatedAt
}
```

### `sensor_data`
```js
{
  farmerId, deviceId,
  nitrogen, phosphorous, potassium,
  soil_moisture, soil_ph, soil_temp,
  timestamp, createdAt
}
```

### `availability_slots`
```js
{
  agriculturalistId, date: "2025-11-05",
  slotTime: "09:30", slotEndTime: "10:00",
  isBooked: false, bookedBy: null,
  createdAt
}
```
**Index**: `{ agriculturalistId: 1, date: 1, slotTime: 1 }` (unique)

### `appointments`
```js
{
  farmerId, agriculturalistId, slotId,
  date, slotTime, slotEndTime,
  status: "booked"|"cancelled"|"completed",
  createdAt
}
```

---

## MongoDB CLI Commands

```bash
mongosh
use agro_intel
```

```js
// List collections
show collections

// View farmers
db.farmers.find().pretty()

// Find by email
db.farmers.findOne({email: "ram@example.com"})

// View sensor data
db.sensor_data.find({"farmerId": "FARM123456"}).sort({timestamp: -1})

// Check indexes
db.availability_slots.getIndexes()
```

---

**Project Maintained With Love for Farmers & Agricultural Experts**

---
