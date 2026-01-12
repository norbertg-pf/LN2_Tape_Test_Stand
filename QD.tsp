-- Shared variable for sending data
local share_data = ""
local share_send_now = 0

function main()

	reset()

    -- Number of measurements
    local N = 10000
    -- Delay between readings (seconds)
    local dt = 0.0
	local v_treshold =  TRESHOLD --0.2e-3
	local QD = 0
    -- Create a reading buffer
    QDbuf = buffer.make(N, buffer.STYLE_WRITABLE_FULL)
	buffer.write.format(QDbuf, buffer.UNIT_VOLT, buffer.DIGITS_4_5)
    QDbuf.clear()
    QDbuf.fillmode = buffer.FILL_CONTINUOUS
	
	channel.open("allslots")
	channel.write("121", 0)
	channel.write("122", 255)
	channel.write("122", 0)
	channel.close("101")
	
	trigger.extin.clear()

	trigger.extin.wait(1000)

    -- Configure the DMM to measure DC voltage
    dmm.measure.func = dmm.FUNC_DC_VOLTAGE
    dmm.measure.nplc = 0.5   -- integration period

    -- Clear buffer and set fill mode

	display.changescreen(display.SCREEN_GRAPH)
	display.activebuffer = QDbuf
    -- Take measurements
	timer.cleartime()

    while 1 do
        local t = timer.gettime()
		local v = dmm.measure.read()
        buffer.write.reading(QDbuf, v, t)  -- store timestamp + value
		if (v>v_treshold or v<-v_treshold) and QD == 0 and t > 3  then
			channel.write("121", 255)
			channel.write("122", 0)
			print("QD")
			QD = 1
		end
		-- Prepare data for LAN sender thread
    	share_data = string.format("%.6f,%.9f", t, v)  -- time,value
    	print(share_data)
		delay(dt)                        -- wait


    end

end

-- Start the thread

main()
