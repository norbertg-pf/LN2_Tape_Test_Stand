import pyvisa
import datetime
import time
import csv
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
import threading
from typing import Iterable, List, Tuple, Union
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import TDK_PSU_Control as PSU
import os

measurement_running = False
times = []
currents = []
voltages = []
start_time = time.time()
# ---------------- Tkinter GUI ---------------- #
root = tk.Tk()
root.title("DMM7510 Live Measurement")

csv_filename_var = tk.StringVar(value=datetime.datetime.now().strftime("%m%d%Y_%H%M%S"))
treshold_var = tk.StringVar(value="0.2")
ramprate_var = tk.StringVar(value="20")
maxcurrent_var = tk.StringVar(value="500")
IP_PSU_var = tk.StringVar(value="169.254.249.195")   # PSU IP
IP_DMM_var = tk.StringVar(value="169.254.169.37")    # DMM IP

# --- GUI Layout ---
ttk.Label(root, text="CSV Filename:").grid(row=0, column=0)
filename_entry = ttk.Entry(root, textvariable=csv_filename_var, width=20)
filename_entry.grid(row=0, column=1)

ttk.Label(root, text="PSU IP:").grid(row=0, column=2)
ttk.Entry(root, textvariable=IP_PSU_var, width=20).grid(row=0, column=3)

ttk.Label(root, text="DMM IP:").grid(row=0, column=4)
ttk.Entry(root, textvariable=IP_DMM_var, width=20).grid(row=0, column=5)

ttk.Label(root, text="QD treshold [mV] = ").grid(row=1, column=0)
ttk.Entry(root, textvariable=treshold_var, width=20).grid(row=1, column=1)

ttk.Label(root, text="Ramp rate [A/s] = ").grid(row=1, column=2)
ttk.Entry(root, textvariable=ramprate_var, width=20).grid(row=1, column=3)

ttk.Label(root, text="Max current [A] = ").grid(row=1, column=4)
ttk.Entry(root, textvariable=maxcurrent_var, width=20).grid(row=1, column=5)

start_button = ttk.Button(root, text="Start Measurement")
start_button.grid(row=2, column=0)

stop_button = ttk.Button(root, text="Stop", state=tk.DISABLED)
stop_button.grid(row=2, column=1)

#stop_psu = ttk.Button(root, text="Stop_psu")
#stop_psu.grid(row=2, column=2)

exit_button = ttk.Button(root, text="Exit")
exit_button.grid(row=2, column=3)

# ---------------- PSU constants ---------------- #
# Define your sequence here:
# Each tuple is (I_target [A], ramp_time [s])
Step = Tuple[float, float]  # (I_target [A], T_ramp [s])
PORT = 8003
SOCKET_TIMEOUT = 5.0   # seconds
# Status bits in STAT:OPER:COND?
SSA_BIT = 6   # Sequencer Step Active
TWI_BIT = 3   # Trigger Wait

# ---------------- Program Keithley DMM ---------------- #
def write_script_to_Keithley():
    rm = pyvisa.ResourceManager()
    global inst
    try:
        print("TCPIP0::" + IP_DMM_var.get() + "::inst0::INSTR")
        inst = rm.open_resource("TCPIP0::" + IP_DMM_var.get() + "::inst0::INSTR")
    except Exception as e:
        print(e)
        messagebox.showinfo("Failed to communicate with Keithley!", e)

    # Load TSP script into memory
    with open("QD.tsp", "r") as f:
        script_content = f.read()
    script_content = script_content.replace("TRESHOLD", str(float(treshold_var.get())/1e3))

    script_name = "QD"
    
    inst.write("abort")
    inst.write("script.delete(\"" + script_name + "\")")    # Delete last saved script
    inst.write("loadscript " + script_name)
    inst.write(script_content)                              # Write current script onto the memory
    inst.write("endscript")
    inst.write(script_name + ".save()")                     # Save the script, FullDiodeTest, into nonvolatile memory
    inst.write(script_name + ".run()")

# ---------------- Create dir and file -------------- #
def open_file():
    if not os.path.exists("data\\"):
        os.makedirs("data\\")
    filename = f"data\\" + filename_entry.get() + ".csv"
    while os.path.exists(filename):
        filename_entry.delete(0, tk.END)
        filename_entry.insert(0, datetime.datetime.now().strftime("%m%d%Y_%H%M%S"))
        filename = f"data\\" + filename_entry.get() + ".csv"
    return open("data\\" + filename_entry.get() + ".csv", "w", newline="")

# ---------------- Measurement Start ---------------- #
def start_measurement():
    global measurement_running, file, csv_writer
    measurement_running = True

    write_script_to_Keithley()

    time.sleep(1)

    file = open_file()
    csv_writer = csv.writer(file)
    csv_writer.writerow(["timestamp", "value"])

    start_button.config(state=tk.DISABLED)
    stop_button.config(state=tk.NORMAL)

    # Start data acquisition in background thread
    global thread_readdata
    thread_readdata = threading.Thread(target=read_data, daemon=True)
    thread_readdata.start()
    steps: List[Step] = [
        (0, 1.0),
        (0, 1.0),
        (float(maxcurrent_var.get()), float(maxcurrent_var.get())/float(ramprate_var.get())),
        (float(maxcurrent_var.get()), 1.0),
        (0, float(maxcurrent_var.get())/float(ramprate_var.get())),
        (0, 1.0),
    ]
    print (steps)
    
    PSU.program_current_wave_sequence(
        ip=IP_PSU_var.get(),
        port=PORT,
        steps=steps,
        i_start=0.0,
        counter=1,
        trigger_delay=0.0,
        continuous_init=False,
        store_cell=None,
    )
    start_graph()
    PSU.trigger_PSU()

# ---------------- Graph Start ---------------- #
def start_graph():

    global fig, ax, canvas, line
    fig, ax = plt.subplots()
    line, = ax.plot([], [], marker='o', linestyle='-')

    canvas = FigureCanvasTkAgg(fig, master=root)
    canvas.get_tk_widget().grid(row=3, column=0, columnspan=6)
    update_graph()

# ---------------- Read and save data from DMM ---------------- #
def read_data():
    i=0; qd = 0; qd_time = 0; error = 0
    global measurement_running
    while measurement_running:
        try:
            i=i+1
            data = inst.read().strip()
            #data = str(time.time()) + ",0.002340"
            if data == "QD":
                qd = 1
                qd_time = time.time()
                print("QD at: ", qd_time)
            if qd == 0:
                t_str, v_str = data.split(",")
                a_str = round((float(t_str) - 1) * float(ramprate_var.get()),3)
            else:
                t_str, v_str = data.split(",")
                a_str = 0
            #timestamp = (time.time() - start_time)
            #voltage = float(v_str)

            csv_writer.writerow([t_str, a_str, v_str])
            file.flush()
                    # Add to data arrays
            if i%15 == 0:
                currents.append(float(a_str))
                voltages.append(float(v_str))
                i=0
            if qd == 1 and qd_time + 1 < time.time():
                print("stop_collection")
                measurement_running = False
                
        except Exception as e:
            print(e)
            error += 1
            if error > 3:
                stop_measurement()

        time.sleep(0.01)   # 100 Hz = 0.01s delay

# ---------------- Update graph 10Hz ---------------- #
def update_graph():
    if currents:
        # Update Graph
        line.set_ydata(voltages)
        line.set_xdata(currents)
        ax.relim()
        ax.autoscale_view()
        ax.set_xlabel("Current (A)")
        ax.set_ylabel("Voltage (V)")
        ax.set_title("DMM7510 Live Measurement")
        canvas.draw()

    if measurement_running:
        root.after(200, update_graph)  # 5 Hz refresh rate

# ---------------- Measurement Stop ---------------- #
def stop_measurement():
    global measurement_running, thread_readdata
    measurement_running = False
    start_button.config(state=tk.ACTIVE)
    PSU.abort_PSU()
    
    if thread_readdata.is_alive():
        thread_readdata.join()   # <-- waits until the thread finishes
    
    try:
        if file:
            file.close()
    except:
        pass
    
    try:
        inst.close()
    except:
        pass


    messagebox.showinfo("Stopped", "Measurement ended. File saved.")
    #root.destroy()

# ---------------- Abort Stop ---------------- #
def stop_PSU():
    PSU.abort_PSU()
    try:
        if file:
            file.close()
    except:
        pass

def exit():
    root.destroy()

# ---------------- GUI Button Actions ---------------- #
start_button.config(command=start_measurement)
stop_button.config(command=stop_measurement)
#stop_psu.config(command=stop_PSU)
exit_button.config(command=exit)

# ---------------- Start GUI ---------------- #
root.mainloop()