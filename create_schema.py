from pymongo import MongoClient, ASCENDING, DESCENDING
from dotenv import load_dotenv
import os
import logging


# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# Load environment variables
load_dotenv()


def create_database_schema():
    """Create MongoDB database, collections, and indexes for Agro-Intel"""

    try:
        # Connect to MongoDB
        client = MongoClient(os.getenv('MONGO_URI'))
        db = client['agro_intel']
        logger.info("Connected to MongoDB")

        # ================= CREATE COLLECTIONS =================

        # 1. Farmers Collection
        if 'farmers' not in db.list_collection_names():
            db.create_collection('farmers')
            logger.info("Created 'farmers' collection")
        else:
            logger.info("'farmers' collection already exists")
        farmers_collection = db['farmers']

        # Create indexes for farmers
        farmers_collection.create_index([("email", ASCENDING)], unique=True)
        farmers_collection.create_index([("mobileNumber", ASCENDING)], unique=True)
        farmers_collection.create_index([("deviceId", ASCENDING)])
        farmers_collection.create_index([("state", ASCENDING)])
        farmers_collection.create_index([("district", ASCENDING)])
        farmers_collection.create_index([("cityVillage", ASCENDING)])
        farmers_collection.create_index([("isEmailVerified", ASCENDING)])
        farmers_collection.create_index([("createdAt", DESCENDING)])
        logger.info("Created indexes for 'farmers' collection")

        # 2. Agriculturalists Collection
        if 'agriculturalists' not in db.list_collection_names():
            db.create_collection('agriculturalists')
            logger.info("Created 'agriculturalists' collection")
        else:
            logger.info("'agriculturalists' collection already exists")
        agriculturalists_collection = db['agriculturalists']

        # Create indexes for agriculturalists
        agriculturalists_collection.create_index([("email", ASCENDING)], unique=True)
        agriculturalists_collection.create_index([("mobileNumber", ASCENDING)], unique=True)
        agriculturalists_collection.create_index([("state", ASCENDING)])
        agriculturalists_collection.create_index([("district", ASCENDING)])
        agriculturalists_collection.create_index([("cityVillage", ASCENDING)])
        agriculturalists_collection.create_index([("pincode", ASCENDING)])
        agriculturalists_collection.create_index([("isAvailable", ASCENDING)])
        agriculturalists_collection.create_index([("isEmailVerified", ASCENDING)])
        agriculturalists_collection.create_index([("createdAt", DESCENDING)])
        logger.info("Created indexes for 'agriculturalists' collection")

        # 9. Pending Verifications Collection
        existing_collections = db.list_collection_names()
        if 'pending_verifications' not in existing_collections:
         db.create_collection('pending_verifications')
         logger.info("Created 'pending_verifications' collection")
        else:
            logger.info("'pending_verifications' collection already exists")
        pending_verifications_collection = db['pending_verifications']

        # Create indexes for pending_verifications
        pending_verifications_collection.create_index([("email", ASCENDING)], unique=False)
        pending_verifications_collection.create_index([("status", ASCENDING)])
        pending_verifications_collection.create_index([("status", ASCENDING), ("submittedAt", DESCENDING)])
        pending_verifications_collection.create_index([("email", ASCENDING), ("status", ASCENDING)])
        logger.info("Created indexes for 'pending_verifications' collection")

        # 3. Sensor Data Collection
        if 'sensor_data' not in db.list_collection_names():
            db.create_collection('sensor_data')
            logger.info("Created 'sensor_data' collection")
        else:
            logger.info("'sensor_data' collection already exists")
        sensor_data_collection = db['sensor_data']

        # Create indexes for sensor_data
        sensor_data_collection.create_index([("farmerId", ASCENDING)])
        sensor_data_collection.create_index([("deviceId", ASCENDING)])
        sensor_data_collection.create_index([("timestamp", DESCENDING)])
        sensor_data_collection.create_index([("farmerId", ASCENDING), ("timestamp", DESCENDING)])
        sensor_data_collection.create_index([("farmerId", ASCENDING), ("deviceId", ASCENDING)])
        logger.info("Created indexes for 'sensor_data' collection")

        # 4. Availability Slots Collection
        if 'availability_slots' not in db.list_collection_names():
            db.create_collection('availability_slots')
            logger.info("Created 'availability_slots' collection")
        else:
            logger.info("'availability_slots' collection already exists")
        availability_slots_collection = db['availability_slots']

        # Create indexes for availability_slots
        availability_slots_collection.create_index([("agriculturalistId", ASCENDING)])
        availability_slots_collection.create_index([("date", ASCENDING)])
        availability_slots_collection.create_index([("slotTime", ASCENDING)])
        availability_slots_collection.create_index([("isBooked", ASCENDING)])
        availability_slots_collection.create_index([("agriculturalistId", ASCENDING), ("date", ASCENDING)])
        availability_slots_collection.create_index([("agriculturalistId", ASCENDING), ("date", ASCENDING), ("isBooked", ASCENDING)])
        availability_slots_collection.create_index([("agriculturalistId", ASCENDING), ("date", ASCENDING), ("slotTime", ASCENDING)], unique=True)
        logger.info("Created indexes for 'availability_slots' collection")

        # 5. Appointments Collection
        if 'appointments' not in db.list_collection_names():
            db.create_collection('appointments')
            logger.info("Created 'appointments' collection")
        else:
            logger.info("'appointments' collection already exists")
        appointments_collection = db['appointments']

        # Create indexes for appointments
        appointments_collection.create_index([("farmerId", ASCENDING)])
        appointments_collection.create_index([("agriculturalistId", ASCENDING)])
        appointments_collection.create_index([("slotId", ASCENDING)])
        appointments_collection.create_index([("status", ASCENDING)])
        appointments_collection.create_index([("date", DESCENDING)])
        appointments_collection.create_index([("createdAt", DESCENDING)])
        appointments_collection.create_index([("farmerId", ASCENDING), ("status", ASCENDING)])
        appointments_collection.create_index([("agriculturalistId", ASCENDING), ("status", ASCENDING)])
        appointments_collection.create_index([("farmerId", ASCENDING), ("date", ASCENDING)])
        # NEW: Required by farmer-send-sensor-data endpoint to verify active appointment
        # between a specific farmer and agriculturalist before allowing sensor data sharing
        appointments_collection.create_index([("farmerId", ASCENDING), ("agriculturalistId", ASCENDING), ("status", ASCENDING)])
        logger.info("Created indexes for 'appointments' collection")

        # 6. Counters Collection (for ID generation if needed)
        if 'counters' not in db.list_collection_names():
            db.create_collection('counters')
            logger.info("Created 'counters' collection")
        else:
            logger.info("'counters' collection already exists")
        counters_collection = db['counters']

        # Initialize counters
        if not counters_collection.find_one({"_id": "farmerId"}):
            counters_collection.insert_one({"_id": "farmerId", "sequence_value": 0})
            logger.info("Initialized farmerId counter")
        else:
            logger.info("farmerId counter already exists")

        if not counters_collection.find_one({"_id": "agriculturalistId"}):
            counters_collection.insert_one({"_id": "agriculturalistId", "sequence_value": 0})
            logger.info("Initialized agriculturalistId counter")
        else:
            logger.info("agriculturalistId counter already exists")

        if not counters_collection.find_one({"_id": "appointmentId"}):
            counters_collection.insert_one({"_id": "appointmentId", "sequence_value": 0})
            logger.info("Initialized appointmentId counter")
        else:
            logger.info("appointmentId counter already exists")

        # 7. OTPs Collection
        if 'otps' not in db.list_collection_names():
            db.create_collection('otps')
            logger.info("Created 'otps' collection")
        else:
            logger.info("'otps' collection already exists")
        otps_collection = db['otps']

        # Create indexes for otps (with TTL for automatic expiration)
        otps_collection.create_index([("userId", ASCENDING)])
        otps_collection.create_index([("email", ASCENDING)])
        otps_collection.create_index([("createdAt", ASCENDING)], expireAfterSeconds=600)  # 10 minutes
        logger.info("Created indexes for 'otps' collection with TTL of 10 minutes")

        # 8. Pending Updates Collection
        if 'pending_updates' not in db.list_collection_names():
            db.create_collection('pending_updates')
            logger.info("Created 'pending_updates' collection")
        else:
            logger.info("'pending_updates' collection already exists")
        pending_updates_collection = db['pending_updates']

        # Create indexes for pending_updates (with TTL for automatic expiration)
        # Handles all pending types: register_farmer, register_agriculturalist,
        # update_password_farmer, update_password_agriculturalist, forgot_password
        pending_updates_collection.create_index([("userId", ASCENDING)])
        pending_updates_collection.create_index([("type", ASCENDING)])
        pending_updates_collection.create_index([("email", ASCENDING)])
        pending_updates_collection.create_index([("userId", ASCENDING), ("type", ASCENDING)])
        pending_updates_collection.create_index([("createdAt", ASCENDING)], expireAfterSeconds=600)  # 10 minutes
        logger.info("Created indexes for 'pending_updates' collection with TTL of 10 minutes")

        # ================= PRINT SUMMARY =================
        logger.info("\n" + "="*70)
        logger.info("DATABASE SCHEMA CREATED SUCCESSFULLY FOR AGRO-INTEL")
        logger.info("="*70)
        logger.info(f"Database: agro_intel")
        logger.info(f"\nCollections created/verified:")
        logger.info(f"  1. farmers")
        logger.info(f"     - Indexes: email (unique), mobileNumber (unique), deviceId,")
        logger.info(f"                state, district, cityVillage, isEmailVerified, createdAt")
        logger.info(f"\n  2. agriculturalists")
        logger.info(f"     - Indexes: email (unique), mobileNumber (unique), state,")
        logger.info(f"                district, cityVillage, pincode, isAvailable,")
        logger.info(f"                isEmailVerified, createdAt")
        logger.info(f"\n  3. sensor_data")
        logger.info(f"     - Indexes: farmerId, deviceId, timestamp,")
        logger.info(f"                farmerId+timestamp, farmerId+deviceId")
        logger.info(f"\n  4. availability_slots")
        logger.info(f"     - Indexes: agriculturalistId, date, slotTime, isBooked,")
        logger.info(f"                compound indexes, unique constraint on agri+date+time")
        logger.info(f"\n  5. appointments")
        logger.info(f"     - Indexes: farmerId, agriculturalistId, slotId, status,")
        logger.info(f"                date, createdAt, compound indexes,")
        logger.info(f"                farmerId+agriculturalistId+status (for sensor data sharing)")
        logger.info(f"\n  6. counters")
        logger.info(f"     - Initialized: farmerId, agriculturalistId, appointmentId")
        logger.info(f"\n  7. otps")
        logger.info(f"     - Indexes: userId, email, createdAt (TTL: 10 minutes)")
        logger.info(f"\n  8. pending_updates")
        logger.info(f"     - Indexes: userId, type, email, compound indexes")
        logger.info(f"                createdAt (TTL: 10 minutes)")
        logger.info(f"\n  9. pending_verifications")
        logger.info(f"     - Indexes: email, status, status+submittedAt, email+status")
        logger.info(f"     - Supports admin approval and rejection workflow")
        logger.info(f"     - Handles types: register_farmer, register_agriculturalist,")
        logger.info(f"                      update_password_farmer, update_password_agriculturalist,")
        logger.info(f"                      forgot_password")
        logger.info("="*70)
        logger.info("\nAll collections are ready for use!")
        logger.info("TTL indexes will automatically delete expired OTPs and pending updates.")
        logger.info("="*70 + "\n")

        # Close connection
        client.close()
        logger.info("MongoDB connection closed")

        return True

    except Exception as e:
        logger.error(f"Error creating database schema: {str(e)}")
        return False


if __name__ == "__main__":
    success = create_database_schema()
    if success:
        print("\n✅ Database schema setup completed successfully!")
    else:
        print("\n❌ Database schema setup failed. Check logs for details.")