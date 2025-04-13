#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <WiFiManager.h> // <-- ADDED: Include WiFiManager library

// --- REMOVED Hardcoded Credentials ---
// const char* ssid = "Saat_Service";
// const char* password = "service@2024";

// === Flask Server URL ===
const char* flaskURL = "https://vending-machine-app-lolz.onrender.com";

// === Unique vending ID ===
const String vend_id = "v3";

// === Pin Config ===
const int motorPin1 = 7;
const int motorPin2 = 6;
const int switchPin1 = 3; // Using internal pull-down
const int switchPin2 = 4; // Using internal pull-down

// === State Tracking ===
bool motor1Running = false;
bool motor2Running = false;
bool motor1SignalReceived = false;
bool motor2SignalReceived = false;
int previousSwitchState1 = LOW;
int previousSwitchState2 = LOW;

// Flags to track the stable, debounced state of the switches
bool switch1Activated = false;
bool switch2Activated = false;

// === Debounce Timing ===
const unsigned long debounceDelay = 50;  // 50 ms debounce delay
unsigned long lastDebounceTime1 = 0;     // Last debounce time for switch 1
unsigned long lastDebounceTime2 = 0;     // Last debounce time for switch 2

// === Polling Control ===
unsigned long lastPollTime = 0;
const unsigned long pollInterval = 500;  // ms Poll every 0.5 seconds

// === WiFiManager Configuration ===
#define CONFIG_PORTAL_TIMEOUT 180 // Timeout for configuration portal in seconds (3 minutes)
const char* CONFIG_AP_NAME = "VendingMachineSetup"; // Name of the AP if WiFi fails

void setup() {
  Serial.begin(115200);
  Serial.println("\n\n--- Vending Machine Booting ---");

  // --- Initialize Hardware FIRST ---
  Serial.println("Initializing hardware pins...");
  pinMode(motorPin1, OUTPUT);
  pinMode(motorPin2, OUTPUT);
  // Use INPUT_PULLDOWN if your switches connect the pin to 3.3V when pressed
  // Use INPUT_PULLUP if your switches connect the pin to GND when pressed
  pinMode(switchPin1, INPUT_PULLDOWN);
  pinMode(switchPin2, INPUT_PULLDOWN);

  digitalWrite(motorPin1, LOW); // Ensure motors are off initially
  digitalWrite(motorPin2, LOW);
  Serial.println("Hardware initialized.");

  // --- Initialize WiFiManager ---
  WiFiManager wifiManager;

  // Optional: Set timeout for portal
  wifiManager.setConfigPortalTimeout(CONFIG_PORTAL_TIMEOUT);

  // Optional: Set callback for when portal is started
  wifiManager.setAPCallback([](WiFiManager *myWiFiManager) {
    Serial.println("\n----- WiFi Configuration Needed -----");
    Serial.print("Connect to Access Point: ");
    Serial.println(myWiFiManager->getConfigPortalSSID());
    Serial.println("Open browser to IP Address: 192.168.4.1");
    Serial.println("--------------------------------------");
    // You could add code here to blink an LED to indicate config mode
  });

   // Optional: Set callback for when configuration is saved
   // This restarts the ESP32 to apply the new settings immediately
   wifiManager.setSaveConfigCallback([]() {
     Serial.println("WiFi Configuration Saved. Restarting device...");
     delay(1000);
     ESP.restart();
   });

  // --- Attempt to Connect or Start Config Portal ---
  Serial.println("Attempting WiFi Connection...");
  // autoConnect blocks until connected, portal is used, or timeout occurs
  if (!wifiManager.autoConnect(CONFIG_AP_NAME)) {
    Serial.println("Failed to connect to WiFi and hit timeout.");
    Serial.println("Restarting ESP to try again...");
    delay(3000);
    ESP.restart();
    delay(5000); // Wait for restart
  }

  // --- If we get here, WiFi is connected! ---
  Serial.println("\n--------------------------");
  Serial.println("✅ Wi-Fi connected!");
  Serial.print("   SSID: ");
  Serial.println(WiFi.SSID()); // Display the connected network name
  Serial.print("   IP Address: ");
  Serial.println(WiFi.localIP());
  Serial.println("--------------------------");
  Serial.println("--- Vending Machine Ready ---");

  // Initialize lastPollTime *after* WiFi is connected
  lastPollTime = millis();
}

void loop() {
  // --- Robustness Check: Ensure WiFi is still connected ---
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("❌ WiFi Disconnected mid-operation!");
    // Option: Attempt to reconnect (might take time)
    // Serial.println("Attempting reconnect...");
    // WiFi.reconnect();
    // delay(5000); // Give it time
    // if (WiFi.status() != WL_CONNECTED) {
    //    Serial.println("Reconnect failed. Restarting...");
    //    delay(1000);
    //    ESP.restart();
    // } else {
    //    Serial.println("Reconnected!");
    // }

    // Option: Simple Restart (often the most reliable)
    Serial.println("Restarting device...");
    delay(1000);
    ESP.restart();
  }

  // 👀 Run motor/switch logic frequently
  handleMotorLogic();

  // 🌐 Poll the server at defined intervals
  if (millis() - lastPollTime >= pollInterval) {
    pollServer();
    lastPollTime = millis(); // Reset the timer AFTER polling
  }

  // Small delay to prevent hammering the CPU and allow background tasks
  delay(10);
}

// ======================================
// === Motor and Switch Logic         ===
// (Keep this function exactly as is) ===
// ======================================
void handleMotorLogic() {
  int currentSwitchState1 = digitalRead(switchPin1);
  int currentSwitchState2 = digitalRead(switchPin2);

  // === Motor 1 ===
  if (motor1SignalReceived) {
    Serial.println("⚙️ [M1] Start signal received from server.");
    digitalWrite(motorPin1, HIGH);  // Turn on the motor
    motor1Running = true;
    motor1SignalReceived = false;   // Clear the signal flag
    switch1Activated = false;       // Reset switch state assumption when starting via signal
    previousSwitchState1 = LOW;     // Reset previous state
    Serial.println("   [M1] Motor ON, awaiting switch press/release.");
  }

  // Debounce and state detection logic for Switch 1
  if (currentSwitchState1 != previousSwitchState1) {
    lastDebounceTime1 = millis(); // Reset debounce timer on change
  }

  if ((millis() - lastDebounceTime1) > debounceDelay) {
    // If the switch state reading has been stable for the debounce period
    if (currentSwitchState1 != switch1Activated) { // If the stable state has changed
      switch1Activated = currentSwitchState1; // Update the stable state

      if (switch1Activated == HIGH) {
        Serial.println("🔼 [M1] Switch 1 Pressed (Stable)");
        // If motor was started by signal, we don't need to turn it on again here
        if (!motor1Running) {
           Serial.println("   (Switch press detected, but motor wasn't running - unexpected?)");
           // Decide if you want to force motor on here or log error
        }
      } else { // switch1Activated == LOW
        Serial.println("🔽 [M1] Switch 1 Released (Stable)");
        if (motor1Running) {
          Serial.println("🛑 [M1] Motor OFF due to switch release.");
          digitalWrite(motorPin1, LOW); // Turn off the motor
          motor1Running = false;
          sendAck(1, "success"); // Send acknowledgment NOW that process is complete
        } else {
           Serial.println("   (Switch release detected, but motor wasn't running)");
        }
      }
    }
  }
  previousSwitchState1 = currentSwitchState1; // Store current reading for next loop comparison

  // === Motor 2 === (Mirrors Motor 1 logic)
  if (motor2SignalReceived) {
    Serial.println("⚙️ [M2] Start signal received from server.");
    digitalWrite(motorPin2, HIGH);
    motor2Running = true;
    motor2SignalReceived = false;
    switch2Activated = false;
    previousSwitchState2 = LOW;
    Serial.println("   [M2] Motor ON, awaiting switch press/release.");
  }

  if (currentSwitchState2 != previousSwitchState2) {
    lastDebounceTime2 = millis();
  }

  if ((millis() - lastDebounceTime2) > debounceDelay) {
    if (currentSwitchState2 != switch2Activated) {
      switch2Activated = currentSwitchState2;

      if (switch2Activated == HIGH) {
        Serial.println("🔼 [M2] Switch 2 Pressed (Stable)");
         if (!motor2Running) {
           Serial.println("   (Switch press detected, but motor wasn't running - unexpected?)");
         }
      } else { // switch2Activated == LOW
        Serial.println("🔽 [M2] Switch 2 Released (Stable)");
        if (motor2Running) {
          Serial.println("🛑 [M2] Motor OFF due to switch release.");
          digitalWrite(motorPin2, LOW);
          motor2Running = false;
          sendAck(2, "success");
        } else {
          Serial.println("   (Switch release detected, but motor wasn't running)");
        }
      }
    }
  }
  previousSwitchState2 = currentSwitchState2;
}


// ======================================
// === Poll the Flask Server          ===
// (Keep this function exactly as is) ===
// ======================================
void pollServer() {
  // Check added at start of loop, but double check is fine
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("❌ [Poll] Wi-Fi not connected. Skipping poll.");
    return; // Exit function if not connected
  }

  HTTPClient http;
  String url = String(flaskURL) + "/get_command?vend_id=" + vend_id;
  Serial.println("📡 [Poll] Sending GET to: " + url);
  http.begin(url);
  http.setTimeout(5000); // 5 second timeout for HTTP request

  int httpCode = http.GET();

  if (httpCode > 0) { // Check for positive HTTP code (includes redirects)
    Serial.printf("   [Poll] HTTP Response Code: %d\n", httpCode);
    if (httpCode == HTTP_CODE_OK) { // Code 200
        String response = http.getString();
        Serial.println("   [Poll] Server response payload: " + response);

        DynamicJsonDocument doc(256); // Adjust size if payload can be larger
        DeserializationError error = deserializeJson(doc, response);

        if (error) {
          Serial.print("   [Poll] deserializeJson() failed: ");
          Serial.println(error.c_str());
        } else {
          // Safely access JSON fields
          if (doc.containsKey("motor_id") && doc.containsKey("action")) {
            int motor_id = doc["motor_id"];
            String action = doc["action"];

            if (action == "start") {
              Serial.printf("   [Poll] Received command: START motor %d\n", motor_id);
              if (motor_id == 1 && !motor1Running) motor1SignalReceived = true; // Only set flag if not already running
              if (motor_id == 2 && !motor2Running) motor2SignalReceived = true; // Only set flag if not already running
            } else {
              Serial.println("   [Poll] Received unknown action: " + action);
            }
          } else {
             Serial.println("   [Poll] JSON response missing 'motor_id' or 'action'.");
          }
        }
    } else {
      Serial.println("   [Poll] Received non-OK HTTP code.");
    }
  } else {
    Serial.printf("❌ [Poll] HTTP GET failed, error: %s\n", http.errorToString(httpCode).c_str());
  }

  http.end(); // Free resources
}

// ======================================
// === Acknowledge to Flask Server    ===
// (Keep this function exactly as is) ===
// ======================================
void sendAck(int motor_id, String status) {
  // Check added at start of loop, but double check is fine
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("❌ [ACK] Wi-Fi not connected. Cannot send ACK.");
    return; // Exit function if not connected
  }

  HTTPClient http;
  String url = String(flaskURL) + "/acknowledge";
  Serial.println("📡 [ACK] Sending POST to: " + url);
  http.begin(url);
  http.addHeader("Content-Type", "application/json");

  DynamicJsonDocument doc(256); // Adjust size if needed
  doc["motor_id"] = motor_id;
  doc["status"] = status;
  doc["vend_id"] = vend_id;

  String requestBody;
  serializeJson(doc, requestBody);
  Serial.println("   [ACK] Request body: " + requestBody);

  int httpCode = http.POST(requestBody);

   if (httpCode > 0) {
    Serial.printf("   [ACK] HTTP Response Code: %d\n", httpCode);
    if (httpCode == HTTP_CODE_OK) {
      String response = http.getString();
      Serial.println("   [ACK] Server response: " + response);
      Serial.println("✅ [ACK] Acknowledgment sent successfully for motor " + String(motor_id));
    } else {
       Serial.println("❌ [ACK] Failed to send acknowledgment (Server returned non-OK code).");
    }
  } else {
    Serial.printf("❌ [ACK] HTTP POST failed, error: %s\n", http.errorToString(httpCode).c_str());
  }

  http.end(); // Free resources
}