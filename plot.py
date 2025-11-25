import csv
import matplotlib.pyplot as plt

# --- Read CSV ---
times = []
voltages = []

with open("data//P1a_11242025_154547.csv", "r") as file:
    csv_reader = csv.reader(file)
    next(csv_reader)  # skip header
    for row in csv_reader:
        times.append((float((row)[1])))    # timestamp
        voltages.append(float(row[2])) # voltage

# --- Plot Data ---
plt.plot(times, voltages, marker='o')
plt.xlabel("Time (s)")
plt.ylabel("Voltage (V)")
plt.title("DMM7510 Measurement Log")
plt.grid(True)
plt.show()