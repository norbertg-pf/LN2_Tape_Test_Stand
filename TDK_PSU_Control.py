#!/usr/bin/env python3
"""
Genesys+ GSP10-1000:
- Program a current WAVE sequence (steps with ramp + dwell)
- Configure BUS trigger source
- Start monitoring/logging
- Wait for user to press Enter, then send *TRG to launch the sequence

Communication: SCPI over TCP/IP (port 8003).
"""

import socket
import time
import csv
import threading
from datetime import datetime
from typing import Iterable, List, Tuple, Union

IP = "169.254.249.195"   # <-- set your PSU IP here
PORT = 8003
SOCKET_TIMEOUT = 5.0   # seconds

# Status bits in STAT:OPER:COND?
SSA_BIT = 6   # Sequencer Step Active
TWI_BIT = 3   # Trigger Wait


# ---------- Low-level SCPI helpers ----------

def scpi_write(sock: socket.socket, cmd: str) -> None:
    """Send a SCPI command (no response expected)."""
    msg = (cmd + "\n").encode("ascii")
    sock.sendall(msg)


def scpi_query(sock: socket.socket, cmd: str) -> str:
    """Send a SCPI query and read one LF-terminated response line."""
    scpi_write(sock, cmd)
    data = b""
    while not data.endswith(b"\n"):
        chunk = sock.recv(4096)
        if not chunk:
            raise RuntimeError(f"Socket closed while waiting for response to {cmd!r}")
        data += chunk
    return data.decode("ascii").strip()


def check_error_queue(sock: socket.socket) -> None:
    """Poll SYST:ERR? until it returns '0,...'. Print any errors."""
    while True:
        err = scpi_query(sock, "SYST:ERR?")
        code_str = err.split(",", 1)[0]
        try:
            code = int(code_str)
        except ValueError:
            print("Unexpected SYST:ERR? response:", err)
            break
        if code == 0:
            break
        print("PSU error:", err)


def stat_oper_cond(sock: socket.socket) -> int:
    """Read STAT:OPER:COND? and return it as an integer."""
    return int(scpi_query(sock, "STAT:OPER:COND?"))


def bit(val: int, n: int) -> int:
    """Return bit n (0/1) from val."""
    return (val >> n) & 1


# ---------- Waveform construction ----------

Step = Tuple[float, float]  # (I_target [A], T_ramp [s])

# ---------- High-level: program sequence and arm (BUS trigger) ----------

def program_current_wave_sequence(
    ip: str,
    port: int,
    steps: Iterable[Step],
    i_start: float = 0.0,
    counter: Union[int, str] = 1,
    trigger_delay: float = 0.0,
    continuous_init: bool = False,
    store_cell: int | None = None,       # e.g. 1..4 or None to skip storing
) -> None:
    """Program a WAVE-mode current sequence and arm it with BUS trigger selected.

    steps: sequence of (I_target [A], T_ramp [s], T_dwell [s])
    i_start: initial current (A) before first step
    counter: number of iterations (1..9999) or 'INF'
    trigger_delay: seconds between *TRG and waveform start
    continuous_init:
      - False: one sequence per INIT (you must re-INIT each time)
      - True: PSU re-arms automatically after each sequence
    store_cell: if not None, store sequence into non-volatile memory cell (1..4)

    Sequence is not started here; you must later send *TRG while TRIG:SOUR BUS.
    """
    curr_points = [step[0] for step in steps]
    time_points = [step[1] for step in steps]
    print(curr_points)
    print(time_points)

    with socket.create_connection((ip, port), timeout=SOCKET_TIMEOUT) as sock:
        print("Connected to PSU for programming.")
        scpi_write(sock, "SYST:LANG SCPI")
        scpi_write(sock, "*CLS")
        scpi_write(sock, "OUTPut:TTLTrg:MODE OFF")
        scpi_write(sock, "ABOR")  # Abort any running sequence
        scpi_write(sock, "CURR:LEV 0")
        # --- Program the WAVE sequence in current ---

        scpi_write(sock, "SOUR:CURR:MODE WAVE")

        wave_curr_str = ",".join(f"{v:.6g}" for v in curr_points)
        scpi_write(sock, f"PROG:WAVE:CURR {wave_curr_str}")

        wave_time_str = ",".join(f"{t:.6g}" for t in time_points)
        scpi_write(sock, f"PROG:WAVE:TIME {wave_time_str}")

        time.sleep(0.2)  # allow processing

        scpi_write(sock, "PROG:STEP AUTO")

        if isinstance(counter, str) and counter.upper().startswith("INF"):
            scpi_write(sock, "PROG:COUN INF")
        else:
            scpi_write(sock, f"PROG:COUN {int(counter)}")

        if store_cell is not None:
            scpi_write(sock, f"PROG:STOR {int(store_cell)}")
            time.sleep(0.2)

        # --- Trigger configuration: BUS + INIT ---

        scpi_write(sock, "TRIG:SOUR BUS")
        scpi_write(sock, f"TRIG:DEL {float(trigger_delay):.6g}")
        scpi_write(sock, f"INIT:CONT {'ON' if continuous_init else 'OFF'}")

        # Turn output ON so the sequence drives the load when triggered.
        scpi_write(sock, "OUTP ON")

        # INIT arms the trigger system; *TRG will actually start the sequence.
        scpi_write(sock, "INIT")

        time.sleep(0.2)
        
        scpi_write(sock, "OUTPut:TTLTrg:MODE FSTR")

        status = stat_oper_cond(sock)
        twi = bit(status, TWI_BIT)
        ssa = bit(status, SSA_BIT)
        print(
            f"STAT:OPER:COND? = {status} (TWI={twi}, SSA={ssa}) "
            f"=> {'waiting for BUS trigger' if twi else 'not in trigger-wait'}"
        )

        check_error_queue(sock)
        print("Programming done, BUS trigger selected and system INITed (armed).")
        time.sleep(1)

        # scpi_write(sock, "*TRG")
        # print("*TRG sent (BUS trigger). Sequence should now start.")


def trigger_PSU():
    with socket.create_connection((IP, PORT), timeout=SOCKET_TIMEOUT) as s:
        scpi_write(s, "SYST:LANG SCPI")
        scpi_write(s, "*TRG")
        print("*TRG sent (BUS trigger). Sequence should now start.")

def abort_PSU():
    with socket.create_connection((IP, PORT), timeout=SOCKET_TIMEOUT) as s:
        scpi_write(s, "ABOR")
        scpi_write(s, "OUTP OFF")
        scpi_write(s, "*TRG")
        print("Abort any running sequence and stop the current.")


# ---------- Monitoring & logging ----------

def monitor_and_log(
    ip: str,
    port: int,
    csv_path: str,
    sample_hz: float = 20.0,
    stop_when_done: bool = True,
    max_seconds: float | None = None,
) -> str:
    """Poll MEAS:VOLT?, MEAS:CURR?, MEAS:POW? and STAT:OPER:COND? at sample_hz.

    Writes CSV with columns:
      time_iso, t_rel_s, volt_V, curr_A, pow_W, TWI, SSA, status_raw

    Stops when:
      - SSA has been 1 at least once AND is now 0 again (sequence finished),
      - OR max_seconds elapsed (if given),
      - OR stop_when_done is False and max_seconds is None (manual termination).
    """
    period = 1.0 / float(sample_hz)
    started = None
    saw_active = False

    with socket.create_connection((ip, port), timeout=SOCKET_TIMEOUT) as s, \
         open(csv_path, "w", newline="") as f:

        print("Connected to PSU for monitoring.")
        scpi_write(s, "SYST:LANG SCPI")

        writer = csv.writer(f)
        writer.writerow([
            "time_iso", "t_rel_s",
            "volt_V", "curr_A", "pow_W",
            "TWI", "SSA", "status_raw",
        ])

        t0 = time.time()
        while True:
            loop_start = time.time()

            v = float(scpi_query(s, "MEAS:VOLT?"))
            i = float(scpi_query(s, "MEAS:CURR?"))
            p = float(scpi_query(s, "MEAS:POW?"))
            status = stat_oper_cond(s)

            now = time.time()
            if started is None:
                started = now
            t_rel = now - started

            twi = bit(status, TWI_BIT)
            ssa = bit(status, SSA_BIT)
            if ssa:
                saw_active = True

            writer.writerow([
                datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
                f"{t_rel:.6f}",
                f"{v:.9g}", f"{i:.9g}", f"{p:.9g}",
                int(twi), int(ssa), status,
            ])

            if max_seconds is not None and (now - t0) >= max_seconds:
                print("Logging stopped due to timeout.")
                break

            if stop_when_done and saw_active and not ssa:
                print("Logging stopped: sequence finished (SSA transitioned 1->0).")
                break

            dt = time.time() - loop_start
            sleep_left = period - dt
            if sleep_left > 0:
                time.sleep(sleep_left)

    print(f"Log saved to {csv_path}")
    return csv_path


# ---------- Top-level orchestration ----------
def main() -> None:
    # Define your sequence here:
    # Each tuple is (I_target [A], ramp_time [s])
    stepss: List[Step] = [
        (0, 1),
        (0, 1),
        (500, 25),
        (500, 1),
        (0, 1),
    ]

    # Program sequence and arm with BUS trigger selected (but do NOT start it).
    program_current_wave_sequence(
        ip=IP,
        port=PORT,
        steps=steps,
        i_start=0.0,
        counter=1,
        trigger_delay=0.0,
        continuous_init=False,
        store_cell=None,
    )

    # Start monitoring in a separate thread so it runs while we wait for user input
    # def monitor_thread() -> None:
    #     monitor_and_log(
    #         ip=IP,
    #         port=PORT,
    #         csv_path="gsp10_capture.csv",
    #         sample_hz=25.0,
    #         stop_when_done=True,
    #         max_seconds=1800.0,
    #     )

    # t = threading.Thread(target=monitor_thread, daemon=False)
    # t.start()

    # Wait for logging thread to finish
    # t.join()
    print("Done.")


if __name__ == "__main__":
    main()
