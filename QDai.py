import pyvisa
import datetime
import time
import csv
import matplotlib.pyplot as plt
import tkinter as tk
from tkinter import ttk, messagebox
import threading
from typing import List, Tuple
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import TDK_PSU_Control as PSU


class KeithleyQD_UI:
    def __init__(self, root):
        self.root = root
        self.root.title("DMM7510 Live Measurement")

        # ---------------- Variables ---------------- #
        self.measurement_running = False
        self.times: List[float] = []
        self.currents: List[float] = []
        self.voltages: List[float] = []

        self.csv_filename_var = tk.StringVar(value=datetime.datetime.now().strftime("%m%d%Y_%H%M%S"))
        self.treshold_var = tk.StringVar(value="0.2")
        self.ramprate_var = tk.StringVar(value="20")
        self.maxcurrent_var = tk.StringVar(value="500")
        self.IP_PSU_var = tk.StringVar(value="169.254.249.195")
        self.IP_DMM_var = tk.StringVar(value="169.254.169.37")

        # ---------------- Build GUI ---------------- #
        self.build_gui()

    # --------------------------------------------------------
    #                BUILD GUI
    # --------------------------------------------------------
    def build_gui(self):
        ttk.Label(root, text="CSV Filename:").grid(row=0, column=0)
        ttk.Entry(root, textvariable=self.csv_filename_var, width=20).grid(row=0, column=1)

        ttk.Label(root, text="PSU IP:").grid(row=0, column=2)
        ttk.Entry(root, textvariable=self.IP_PSU_var, width=20).grid(row=0, column=3)

        ttk.Label(root, text="DMM IP:").grid(row=0, column=4)
        ttk.Entry(root, textvariable=self.IP_DMM_var, width=20).grid(row=0, column=5)

        ttk.Label(root, text="QD threshold [mV]:").grid(row=1, column=0)
        ttk.Entry(root, textvariable=self.treshold_var, width=20).grid(row=1, column=1)

        ttk.Label(root, text="Ramp rate [A/s]:").grid(row=1, column=2)
        ttk.Entry(root, textvariable=self.ramprate_var, width=20).grid(row=1, column=3)

        ttk.Label(root, text="Max current [A]:").grid(row=1, column=4)
        ttk.Entry(root, textvariable=self.maxcurrent_var, width=20).grid(row=1, column=5)

        self.start_button = ttk.Button(root, text="Start Measurement", command=self.start_measurement)
        self.start_button.grid(row=2, column=0)

        self.stop_button = ttk.Button(root, text="Stop", state=tk.DISABLED, command=self.stop_measurement)
        self.stop_button.grid(row=2, column=1)

    # --------------------------------------------------------
    #                KEITHLEY SETUP
    # --------------------------------------------------------
    def write_script_to_Keithley(self):
        rm = pyvisa.ResourceManager()
        try:
            self.inst = rm.open_resource(f"TCPIP0::{self.IP_DMM_var.get()}::inst0::INSTR")
        except Exception as e:
            messagebox.showerror("Keithley Error", f"Failed to connect:\n{e}")
            return False

        with open("QD.tsp", "r") as f:
            script_content = f.read()

        script_content = script_content.replace("TRESHOLD",
                        str(float(self.treshold_var.get()) / 1e3))  # mV → V

        script_name = "QD"
        self.inst.write("abort")
        self.inst.write(f"script.delete('{script_name}')")
        self.inst.write(f"loadscript {script_name}")
        self.inst.write(script_content)
        self.inst.write("endscript")
        self.inst.write(f"{script_name}.save()")
        self.inst.write(f"{script_name}.run()")
        return True

    # --------------------------------------------------------
    #                START MEASUREMENT
    # --------------------------------------------------------
    def start_measurement(self):
        if not self.write_script_to_Keithley():
            return

        self.measurement_running = True
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)

        filename = f"data\\{self.csv_filename_var.get()}.csv"
        self.file = open(filename, "w", newline="")
        self.csv_writer = csv.writer(self.file)
        self.csv_writer.writerow(["timestamp", "current", "voltage"])

        threading.Thread(target=self.read_data, daemon=True).start()

        steps = [
            (0, 1),
            (0, 1),
            (float(self.maxcurrent_var.get()), float(self.maxcurrent_var.get()) / float(self.ramprate_var.get())),
            (float(self.maxcurrent_var.get()), 1),
            (0, float(self.maxcurrent_var.get()) / float(self.ramprate_var.get())),
            (0, 1),
        ]
        PSU.program_current_wave_sequence(self.IP_PSU_var.get(), 8003, steps, 0.0, 1, 0.0, False, None)
        PSU.trigger_PSU()

        self.start_graph()

    # --------------------------------------------------------
    #                DATA READING THREAD
    # --------------------------------------------------------
    def read_data(self):
        i = 0
        qd = 0

        while self.measurement_running:
            try:
                data = self.inst.read().strip()

                if data == "QD":
                    qd = 1
                    continue

                t_str, v_str = data.split(",")
                current = (float(t_str) - 1) * float(self.ramprate_var.get()) if qd == 0 else 0

                self.csv_writer.writerow([t_str, current, v_str])
                self.file.flush()

                if i % 20 == 0:
                    self.currents.append(current)
                    self.voltages.append(float(v_str))
                i += 1

            except Exception as e:
                print("Read error:", e)

            time.sleep(0.01)

    # --------------------------------------------------------
    #                GRAPH
    # --------------------------------------------------------
    def start_graph(self):
        self.fig, self.ax = plt.subplots()
        self.line, = self.ax.plot([], [], marker="o", linestyle="-")

        canvas = FigureCanvasTkAgg(self.fig, master=self.root)
        canvas.get_tk_widget().grid(row=3, column=0, columnspan=6)
        self.canvas = canvas
        self.update_graph()

    def update_graph(self):
        if self.currents:
            self.line.set_xdata(self.currents)
            self.line.set_ydata(self.voltages)
            self.ax.relim()
            self.ax.autoscale_view()
            self
