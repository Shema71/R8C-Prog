import sys   
from PyQt5 import QtWidgets, uic
from PyQt5.QtWidgets import QFileDialog, QMessageBox
import serial
import serial.tools.list_ports
import time

class R8CProgrammerApp(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        uic.loadUi("r8c_programmer.ui", self)

        self.btnRead.clicked.connect(self.read_flash)
        self.btnWrite.clicked.connect(self.write_flash)
        self.btnVerify.clicked.connect(self.verify_flash)
        self.btnBoot.clicked.connect(self.boot_controller_mode3)
        self.actionOpenHex.triggered.connect(self.open_file)
        self.actionSaveHex.triggered.connect(self.save_file)
        self.btnRefreshPorts.clicked.connect(self.refresh_serial_ports)
        self.comboBoxSerialPorts.currentIndexChanged.connect(self.serial_port_changed)

        self.ser = None
        self.refresh_serial_ports()
        self.lineEditStartAddr.setText("0x4000")
        self.lineEditEndAddr.setText("0x40FF")

    def log(self, text):
        self.console.appendPlainText(text)
        self.statusbar.showMessage(text)

    def delay_precise_ms(self, ms):
        target = time.perf_counter() + ms / 1000.0
        while time.perf_counter() < target:
            pass

    def refresh_serial_ports(self):
        self.comboBoxSerialPorts.clear()
        ports = serial.tools.list_ports.comports()
        for port in ports:
            self.comboBoxSerialPorts.addItem(port.device)
        self.statusbar.showMessage("Портовете са обновени.")

    def serial_port_changed(self, index):
        if self.ser:
            try:
                self.ser.close()
            except Exception as e:
                self.log(f"Грешка при затваряне на порт: {e}")
            self.ser = None

        port_name = self.comboBoxSerialPorts.currentText()
        if port_name:
            try:
                # Увеличен timeout за по-бавно четене при 9600
                self.ser = serial.Serial(port_name, 9600, timeout=0.5)
                self.statusbar.showMessage(f"Свързан с {port_name} @9600")
                self.log(f"Свързан с {port_name} @9600")
            except Exception as e:
                self.log(f"Неуспешен опит за отваряне {port_name} @9600: {e}")
                QMessageBox.critical(self, "Грешка", f"Не може да се отвори порт {port_name}.")
                self.ser = None

    def open_file(self):
        fname, _ = QFileDialog.getOpenFileName(self, "Open File", "", "HEX Files (*.hex *.mot *.bin);;All Files (*)")
        if fname:
            try:
                with open(fname, "rb") as f:
                    data = f.read()
                self.hexViewer.setPlainText(self.format_hex_view(data))
                self.statusbar.showMessage(f"Файл {fname} зареден успешно.")
            except Exception as e:
                QMessageBox.critical(self, "Грешка", f"Не може да се отвори файла: {e}")

    def save_file(self):
        fname, _ = QFileDialog.getSaveFileName(self, "Save File", "", "HEX Files (*.hex *.mot *.bin);;All Files (*)")
        if fname:
            try:
                text = self.hexViewer.toPlainText()
                # Извличане на hex байтове от форматираната визуализация
                hex_data = ''.join(line[10:58].strip().replace(' ', '') for line in text.splitlines() if line)
                data = bytes.fromhex(hex_data)
                with open(fname, "wb") as f:
                    f.write(data)
                self.statusbar.showMessage(f"Файлът е записан успешно: {fname}")
            except Exception as e:
                QMessageBox.critical(self, "Грешка", f"Не може да се запише файла: {e}")

    def send_command_and_receive_clean(self, cmd_bytes, expected_response_len=256, timeout_ms=200):
        if not self.ser or not self.ser.is_open:
            self.log("Портът не е отворен!")
            return b''

        self.ser.reset_input_buffer()
        self.ser.write(cmd_bytes)
        self.ser.flush()
        self.delay_precise_ms(timeout_ms)

        data = self.ser.read(self.ser.in_waiting)
        if data.startswith(cmd_bytes):
            data = data[len(cmd_bytes):]
            self.log("Ехото е успешно премахнато от приетите данни.")
        else:
            self.log("Предупреждение: Не беше открито точно ехо в началото на отговора.")

        return data

    def format_hex_view(self, data: bytes) -> str:
        lines = []
        for i in range(0, len(data), 16):
            chunk = data[i:i+16]
            hex_bytes = ' '.join(f'{b:02X}' for b in chunk)
            ascii_text = ''.join(chr(b) if 32 <= b <= 126 else '.' for b in chunk)
            lines.append(f'{i:08X}  {hex_bytes:<47}  {ascii_text}')
        return '\n'.join(lines)

    def read_flash(self):
        if not self.ser or not self.ser.is_open:
            QMessageBox.warning(self, "Внимание", "Сериен порт не е отворен!")
            return

        try:
            start_addr_str = self.lineEditStartAddr.text().strip()
            start_addr = int(start_addr_str, 16)

            if (start_addr & 0xFF) != 0:
                self.log("❌ Началният адрес трябва да е на страница.")
                return

            mid_addr = (start_addr >> 8) & 0xFF
            high_addr = (start_addr >> 16) & 0xFF

            cmd = bytes([0xFF, mid_addr, high_addr])
            self.log(f"Изпращам команда за четене страница от адрес 0x{start_addr:06X} ({cmd.hex().upper()})")

            self.ser.reset_input_buffer()
            self.ser.write(cmd)
            self.ser.flush()

            # Четене циклично с таймаут 1 секунда, докато съберем всички 256 + 3 байта
            expected_len = 256 + len(cmd)
            received = b''
            start_time = time.time()
            timeout_sec = 1.0

            while len(received) < expected_len and (time.time() - start_time) < timeout_sec:
                chunk = self.ser.read(expected_len - len(received))
                if not chunk:
                    break
                received += chunk

            raw_data = received

            self.log(f"Raw data (hex): {raw_data.hex().upper()}")

            # Премахване на ехо - ако започва с командата, я изрязваме
            if raw_data.startswith(cmd):
                response = raw_data[len(cmd):]
                self.log("Ехото е успешно премахнато от приетите данни.")
            else:
                response = raw_data
                self.log("Предупреждение: Не беше открито точно ехо в началото на отговора.")

            if len(response) == 256:
                self.log("✅ Прочетени 256 байта от флаш памет.")
                self.hexViewer.setPlainText(self.format_hex_view(response))
            else:
                self.log(f"❌ Получени само {len(response)} байта вместо 256.")
                self.log(f"Получено (hex): {response.hex().upper()}")

        except ValueError:
            self.log("❌ Невалиден адрес. Въведете адрес в HEX формат, напр. 0x4000")
        except Exception as e:
            self.log(f"Грешка при четене: {e}")

    def write_flash(self):
        QMessageBox.information(self, "Инфо", "Функцията не е имплементирана.")

    def verify_flash(self):
        QMessageBox.information(self, "Инфо", "Функцията не е имплементирана.")

    def boot_controller_mode3(self):
        # Проверка дали серийният порт е отворен
        if not self.ser or not self.ser.is_open:
            QMessageBox.warning(self, "Внимание", "Сериен порт не е отворен!")
            return

        try:
            # Последователност за стартиране на контролера в режим MODE 3
            self.ser.dtr = False
            self.log("DTR=HIGH (реално) => Освобождава Tx_Break")

            self.ser.rts = True
            self.log("RTS=LOW (реално) => RESET активен")
            self.delay_precise_ms(200)

            self.ser.dtr = True
            self.log("DTR=LOW (реално) => Заема Tx_Break")

            self.ser.rts = False
            self.log("RTS=HIGH (реално) => RESET Освободен")
            self.delay_precise_ms(200)

            self.ser.rts = True
            self.log("RTS=LOW (реално) => RESET активен")
            self.delay_precise_ms(200)

            self.ser.rts = False
            self.log("RTS=HIGH (реално) => RESET Освободен")
            self.delay_precise_ms(200)

            self.ser.dtr = False
            self.log("DTR=HIGH (реално) => Освобождава Tx_Break")
            self.delay_precise_ms(240)

            # Изпращаме 16 байта 0x00 (BREAK)
            for _ in range(16):
                self.ser.reset_input_buffer()
                self.ser.write(b'\x00')
                self.log("Изпратено: 00")
                self.delay_precise_ms(50)

            self.ser.reset_input_buffer()
            self.ser.write(b'\xB0')  # Стартов байт
            self.delay_precise_ms(5)
            response = self.ser.read(1)

            if response == b'\xB0':
                self.log("✅ Контролерът стартира успешно в MODE 3.")
            else:
                self.log(f"❌ Контролерът не върна B0. Получено: {response.hex().upper() if response else 'празно'}")
                return

            # 🔍 ==== ID CHECK ====
            def check_id(id_bytes):
                self.ser.reset_input_buffer()
                cmd = bytes([0xF5, 0xDF, 0xFF, 0x00, 0x07] + id_bytes)
                self.ser.write(cmd)
                self.ser.flush()
                self.log(f"Изпратено: {cmd.hex().upper()}")
                self.delay_precise_ms(10)

                self.ser.write(b'\x50')
                self.log("Изпратено: 50")
                self.delay_precise_ms(10)

                self.ser.write(b'\x70')
                self.log("Изпратено: 70")
                self.delay_precise_ms(30)

                available = self.ser.in_waiting
                resp = self.ser.read(available)
                self.log(f"Получен статус: {resp.hex().upper()} (дължина {len(resp)})")

                try:
                    i = resp.index(b'\x50')
                    if len(resp) >= i + 4:
                        sdr1 = resp[i + 2]
                        sdr2 = resp[i + 3]
                        if sdr1 == 0x80 and sdr2 == 0x0C:
                            self.log("✅ ID потвърден успешно (SDR10=1, SDR11=1)")
                            return True
                        else:
                            self.log(f"❌ ID не е потвърден. Получено: {sdr1:02X} {sdr2:02X}, Очаквано: 80 0C")
                    else:
                        self.log("❌ Статус отговорът не съдържа достатъчно байтове след 50")
                except ValueError:
                    self.log("❌ Не е открита команда 50 в отговора")

                return False

            # Проверка със 7x00 и след това с 7xFF
            if check_id([0x00] * 7) or check_id([0xFF] * 7):
                self.log("ID проверката премина успешно.")
            else:
                self.log("❌ ID проверка неуспешна.")

        except Exception as e:
            self.log(f"Грешка при бутване: {e}")


def main():
    app = QtWidgets.QApplication(sys.argv)
    window = R8CProgrammerApp()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
