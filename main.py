import datetime
import logging
import sqlite3
from datetime import datetime

import requests
from flask import Flask, request, jsonify, render_template

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)

# Function to connect to the database
def connect_db():
    conn = sqlite3.connect('plant_watering.db')
    return conn


# Initialize the database and create the table (run this once)
def init_db():
    conn = connect_db()
    cursor = conn.cursor()

    # Create the sensors table if it doesn't exist
    cursor.execute('''CREATE TABLE IF NOT EXISTS sensors (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        soil_moisture REAL,
                        temperature REAL,
                        humidity REAL,
                        timestamp TEXT
                     )''')
    conn.commit()
    conn.close()




# API endpoint to receive sensor data
@app.route('/api/sensor_data', methods=['POST'])
def receive_sensor_data():
    try:
        # Get data from the request
        sensor_data = request.json
        soil_moisture = sensor_data.get('soil_moisture')
        temperature = sensor_data.get('temperature')
        humidity = sensor_data.get('humidity')

        # Validate that all required fields are provided
        if soil_moisture is None or temperature is None or humidity is None:
            return jsonify({'error': 'Missing data'}), 400

        # Get the current timestamp
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Insert the data into the database
        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO sensors (soil_moisture, temperature, humidity, timestamp) VALUES (?, ?, ?, ?)",
                       (soil_moisture, temperature, humidity, timestamp))
        conn.commit()
        conn.close()

        return jsonify({'message': 'Data stored successfully'}), 201

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Function to get daily weather data from Open-Meteo API
def get_daily_weather_forecast(latitude, longitude):
    """
    Query the Open-Meteo API for daily weather forecast data.

    Parameters:
    - latitude (float): Latitude of the location.
    - longitude (float): Longitude of the location.

    Returns:
    - dict: A dictionary containing daily temperature and precipitation data.
    """
    url = f"https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}&daily=temperature_2m_max,temperature_2m_min,precipitation_sum&timezone=auto"

    try:
        response = requests.get(url)
        response.raise_for_status()  # Raise an error for bad responses

        weather_data = response.json()
        daily_data = {
            'dates': weather_data['daily']['time'],
            'max_temperatures': weather_data['daily']['temperature_2m_max'],
            'min_temperatures': weather_data['daily']['temperature_2m_min'],
            'precipitation': weather_data['daily']['precipitation_sum']
        }
        print(daily_data)
        return daily_data

    except requests.exceptions.RequestException as e:
        print(f"Error fetching weather data: {e}")
        return None


# Function to analyze watering needs
def analyze_watering_need(daily_forecast, soil_moisture, humidity):
    # Define thresholds
    moisture_threshold = 30.0  # General soil moisture threshold
    critical_moisture_threshold = 10.0  # Critical moisture threshold
    humidity_threshold = 30.0  # Humidity threshold

    # Log input values
    logging.info(f"Soil Moisture: {soil_moisture}, Humidity: {humidity}")

    # Step 1: Check soil moisture first
    if soil_moisture >= moisture_threshold:
        logging.info("Condition Met: Soil moisture is above the threshold, no watering needed.")
        return "No watering needed; soil moisture is sufficient."

    # Step 2: Soil moisture is low, check for rain
    today_precipitation = daily_forecast['precipitation'][0]
    tomorrow_precipitation = daily_forecast['precipitation'][1]

    logging.info(f"Today's Precipitation: {today_precipitation}")
    logging.info(f"Tomorrow's Precipitation: {tomorrow_precipitation}")

    if today_precipitation > 0.3:
        logging.info("Condition Met: Rain expected today, no watering needed despite low soil moisture.")
        return "No watering needed; rain is expected today."

    if tomorrow_precipitation > 0.3:
        if soil_moisture < critical_moisture_threshold:
            logging.info("Condition Met: Rain expected tomorrow, but soil moisture critically low.")
            return "Minimal watering needed; soil moisture critically low, but rain is expected tomorrow."
        logging.info("Condition Met: Rain expected tomorrow, soil moisture low but above critical threshold.")
        return "No watering needed; rain is expected tomorrow and soil moisture is not critically low."

    # Step 3: Check for humidity if no rain expected
    logging.info(f"Humidity: {humidity}")
    if humidity < humidity_threshold:
        logging.info("Condition Met: Low humidity, watering needed.")
        return "Watering needed; humidity is low and no rain is expected."

    # Step 4: If no rain, high temperature increase, or low humidity, watering needed
    logging.info(f"Today's Max Temperature: {daily_forecast['max_temperatures'][0]}")
    logging.info(f"Tomorrow's Max Temperature: {daily_forecast['max_temperatures'][1]}")

    if daily_forecast['max_temperatures'][1] > daily_forecast['max_temperatures'][0] + 2:
        logging.info("Condition Met: Significant temperature increase, watering needed.")
        return "Watering needed; temperature is expected to increase significantly."

    # Step 5: If no rain and moisture below threshold, watering needed
    logging.info("Condition Met: Low soil moisture and no rain or extreme conditions detected, watering needed.")
    return "Watering needed; soil moisture is below threshold and no rain or extreme conditions are expected."


def calculate_dynamic_kc(start_date, current_date=None):
    """
    Calculate the crop coefficient (Kc) dynamically based on growth stages.

    Parameters:
        start_date (datetime): Planting start date.
        current_date (datetime): Current date (default: today).

    Returns:
        float: Current Kc value.
    """
    # Define growth stages and corresponding Kc values
    growth_stages = [
        {"stage": "Initial", "days": 20, "kc": 0.45},  # Emergence
        {"stage": "Development", "days": 30, "kc": 0.75},  # Vegetative Growth
        {"stage": "Mid-Season", "days": 40, "kc": 1.15},  # Tuber Bulking
        {"stage": "Late-Season", "days": 30, "kc": 0.9},  # Maturity
    ]

    if current_date is None:
        current_date = datetime.now()

    # Calculate days elapsed since planting
    days_elapsed = (current_date - start_date).days

    # Determine the current growth stage and Kc value
    cumulative_days = 0
    for stage in growth_stages:
        cumulative_days += stage["days"]
        if days_elapsed <= cumulative_days:
            return stage["kc"]

    # Default to the last stage Kc if beyond defined stages
    return growth_stages[-1]["kc"]


def calculate_water_amount(soil_moisture, area, soil_depth, predicted_rainfall, et0, kc, humidity, field_capacity=30):
    """
    Calculate the amount of water to apply based on soil moisture, area to water, soil depth, predicted rainfall,
    crop water requirements, humidity, and field capacity.

    Parameters:
    - soil_moisture (float): Current soil moisture level (as a percentage).
    - area (float): Area to be watered (in square meters).
    - soil_depth (float): Depth of the soil (in meters).
    - predicted_rainfall (float): Amount of rain expected (in mm).
    - et0 (float): Reference evapotranspiration (in mm/day).
    - kc (float): Crop coefficient.
    - humidity (float): Humidity level as a percentage (0 to 100).
    - field_capacity (float): Field capacity of the soil (as a percentage).

    Returns:
    - float: Amount of water to apply (in liters).
    """

    # Calculate crop evapotranspiration (ETc)
    etc = et0 * kc  # ETc in mm/day

    # Convert soil depth to mm
    soil_depth_mm = soil_depth * 1000  # Convert depth to mm

    # Current moisture in mm based on soil moisture percentage
    current_moisture_mm = (soil_moisture / 100) * soil_depth_mm

    # Maximum allowable moisture based on field capacity
    max_moisture_mm = (field_capacity / 100) * soil_depth_mm

    # Desired moisture based on crop ETc and area, capped by field capacity
    desired_moisture_mm = max(etc * area, max_moisture_mm)  # Total moisture needed for the crop (in mm)

    # Calculate the water deficit, accounting for predicted rainfall
    water_deficit_mm = desired_moisture_mm - current_moisture_mm - (predicted_rainfall * area)

    # Ensure that water deficit is not negative (no need for irrigation if excess water is present)
    water_deficit_mm = max(0, water_deficit_mm)

    # Apply humidity adjustment
    if humidity < 30:
        logging.info(f"Humidity is low ({humidity}%), increasing water by 20%.")
        water_deficit_mm *= 1.2  # Increase by 20% if humidity is low
    elif humidity > 80:
        logging.info(f"Humidity is high ({humidity}%), decreasing water by 10%.")
        water_deficit_mm *= 0.9  # Decrease by 10% if humidity is high

    # Log values for info
    logging.info(f"Current Moisture: {current_moisture_mm} mm")
    logging.info(f"Desired Moisture: {desired_moisture_mm} mm")
    logging.info(f"Predicted Rainfall: {predicted_rainfall} mm")
    logging.info(f"Water Deficit: {water_deficit_mm} mm")

    # Convert the deficit to liters (1 mm over 1 m² equals 1 liter)
    water_deficit_liters = water_deficit_mm * area  # Total water deficit in liters

    return int(water_deficit_liters)


# API  to get Et0 values
def get_et0_from_openmeteo(latitude, longitude):
    """
    Fetch the ET₀ (reference evapotranspiration) from Open-Meteo API for a given location.

    Parameters:
    - latitude (float): Latitude of the location.
    - longitude (float): Longitude of the location.

    Returns:
    - float: The latest ET₀ value in mm/day.
    """
    url = f"https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}&hourly=et0_fao_evapotranspiration&timezone=auto"

    try:
        response = requests.get(url)
        data = response.json()
        # Get the latest ET₀ value from the hourly forecast
        et0_values = data['hourly']['et0_fao_evapotranspiration']
        et0 = et0_values[0]  # Assuming we take the first (latest) value
        if et0 <= 0:
            et0 = 1.0 # Need a better logic for extreme low values
            logging.info(f"Fetched ET₀ from Open-Meteo: {et0} mm/day")

        return et0

    except Exception as e:
        logging.error(f"Failed to fetch ET₀: {e}")
        return None


@app.route('/past_decisions', methods=['GET'])
def past_decisions():
    conn = connect_db()
    cursor = conn.cursor()

    # Fetch past decisions
    cursor.execute("SELECT * FROM decisions LIMIT 10")  # Adjust the SQL query as needed
    decisions = cursor.fetchall()

    # Convert the fetched decisions to a list of dictionaries
    decisions_list = []
    for decision in decisions:
        # Assuming your table has fields: id, decision, timestamp
        decisions_list.append({
            'decision': decision[1],
            'timestamp': decision[2],
            'water_amount': decision[3]
        })

    conn.close()

    return jsonify(decisions_list)  # Return as JSON response


@app.route('/api/watering_decision', methods=['GET'])
def watering_decision():
    # Get the last recorded sensor data
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT soil_moisture, temperature, humidity FROM sensors ORDER BY timestamp DESC LIMIT 1")
    sensor_data = cursor.fetchone()
    conn.close()

    if sensor_data is None:
        return jsonify({'error': 'No sensor data available'}), 404

    soil_moisture, temperature, humidity = sensor_data

    latitude = 11.6000 # SA
    longitude = 78.0000

    daily_forecast = get_daily_weather_forecast(latitude, longitude)
    if daily_forecast:
        # Refined decision logic considering ET, humidity, and dynamic thresholds
        decision = analyze_watering_need(daily_forecast, soil_moisture, humidity)

        # Calculate water amount regardless of the decision
        predicted_rainfall = daily_forecast['precipitation'][1]  # Tomorrow's rainfall
        area = 10  # Example area to be watered in square meters
        soil_depth = 0.2  # Example soil depth in meters
        start_date = datetime(2024, 11, 1)
        et0 = get_et0_from_openmeteo(latitude, longitude)
        kc = calculate_dynamic_kc(start_date)

        # Calculate water amount considering the soil moisture and CWR
        water_amount = calculate_water_amount(soil_moisture, area, soil_depth, predicted_rainfall, et0, kc, humidity)
        logging.info(f"Watering amount in litres: {water_amount}")

        # Check if minimal watering is required (e.g., water deficit but not urgent)
        if water_amount > 0 and "Minimal watering needed" in decision:
            water_amount = int(water_amount) / 2  # Reduce for minimal deficit

        # Double-check water deficit despite "No watering needed"
        if "No watering needed" in decision and water_amount > 0:
            logging.warning(
                f"Water deficit detected despite 'No watering needed' decision. Water deficit: {water_amount} liters")
            # Modify the decision based on water deficit
            decision = f"Warning: Water deficit detected, {water_amount} liters needed."

        # Save the updated decision and water amount to DB
        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO decisions (decision, water_amount) VALUES (?, ?)", (decision, water_amount))
        conn.commit()
        conn.close()

        return jsonify({
            'watering_decision': decision,
            'water_amount_liters': int(water_amount)
        }), 200
    else:
        return jsonify({'error': 'Error fetching weather data'}), 500



def get_sensor_data():
    """
    Fetch the latest sensor data from the SQLite database.
    """
    conn = connect_db()
    cursor = conn.cursor()

    # Fetch the latest record
    cursor.execute('''SELECT temperature, humidity, soil_moisture
                      FROM sensors
                      ORDER BY timestamp DESC LIMIT 1''')
    data = cursor.fetchone()

    # Close the database connection
    conn.close()

    # If no data is present, return default values
    if data:
        return {
            'temperature': data[0],
            'humidity': data[1],
            'soil_moisture': data[2],

        }
    else:
        return {
            'temperature': 0.0,
            'humidity': 0.0,
            'soil_moisture': 0.0,

        }


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/data')
def sensor_data():
    # Fetch sensor data from the SQLite database
    data = get_sensor_data()
    return jsonify(data)
# Run the app
if __name__ == '__main__':
    #init_db()  # Initialize the database if it hasn't been created
    app.run(host='0.0.0.0', port=5000, debug=True)
