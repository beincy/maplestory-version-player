/*
 * ESP32-S3 USB HID 键盘固件
 * 作用: 通过串口接收指令,转发为真实 USB 键盘信号。
 *
 * 串口协议(115200, 行式文本, '\n' 结尾):
 *   DOWN:<键名>\n        按下不放
 *   UP:<键名>\n          松开
 *   TAP:<键名>,<毫秒>\n  按下-延时-松开
 * 键名见下方 nameToKey 映射表(与电脑端 hid_keyboard.py 的 KEY_NAMES 一致)。
 *
 * 烧录说明见 ../../使用手册.md §四。
 * 注意: 代码里的 Serial 是"USB-CDC 串口",与 USB-HID 键盘共存于同一根 USB 线。
 */

#include "USBHIDKeyboard.h"

USBHIDKeyboard Keyboard;

// 键名 -> Arduino 键盘常量
int nameToKey(String name) {
  name.toUpperCase();
  if (name == "SPACE")   return KEY_SPACE;
  if (name == "ENTER")   return KEY_RETURN;
  if (name == "ESC")     return KEY_ESC;
  if (name == "TAB")     return KEY_TAB;
  if (name == "SHIFT")   return KEY_LEFT_SHIFT;
  if (name == "CTRL")    return KEY_LEFT_CTRL;
  if (name == "ALT")     return KEY_LEFT_ALT;
  if (name == "UP")      return KEY_UP_ARROW;
  if (name == "DOWN")    return KEY_DOWN_ARROW;
  if (name == "LEFT")    return KEY_LEFT_ARROW;
  if (name == "RIGHT")   return KEY_RIGHT_ARROW;
  if (name == "INSERT")  return KEY_INSERT;
  if (name == "DELETE")  return KEY_DELETE;
  if (name == "HOME")    return KEY_HOME;
  if (name == "END")     return KEY_END;
  if (name == "PAGEUP")  return KEY_PAGE_UP;
  if (name == "PAGEDOWN") return KEY_PAGE_DOWN;
  // F1~F12
  if (name == "F1")  return KEY_F1;
  if (name == "F2")  return KEY_F2;
  if (name == "F3")  return KEY_F3;
  if (name == "F4")  return KEY_F4;
  if (name == "F5")  return KEY_F5;
  if (name == "F6")  return KEY_F6;
  if (name == "F7")  return KEY_F7;
  if (name == "F8")  return KEY_F8;
  if (name == "F9")  return KEY_F9;
  if (name == "F10") return KEY_F10;
  if (name == "F11") return KEY_F11;
  if (name == "F12") return KEY_F12;
  // 单字符: 字母/数字
  if (name.length() == 1) {
    char c = name.charAt(0);
    if (c >= 'A' && c <= 'Z') return c;       // Arduino 键盘常量与 ASCII 大写一致
    if (c >= '0' && c <= '9') return c;
  }
  return 0;  // 未识别
}

void handleLine(String line) {
  line.trim();
  if (line.length() == 0) return;

  int sep = line.indexOf(':');
  if (sep < 0) return;
  String cmd = line.substring(0, sep);
  cmd.toUpperCase();
  String arg = line.substring(sep + 1);
  arg.trim();

  if (cmd == "DOWN" || cmd == "UP") {
    int key = nameToKey(arg);
    if (key == 0) return;
    if (cmd == "DOWN") Keyboard.press(key);
    else               Keyboard.release(key);
  } else if (cmd == "TAP") {
    int comma = arg.indexOf(',');
    if (comma < 0) return;
    int key = nameToKey(arg.substring(0, comma));
    long ms = arg.substring(comma + 1).toInt();
    if (key == 0) return;
    if (ms < 20) ms = 20;
    if (ms > 3000) ms = 3000;   // 上限 3 秒,防止异常指令卡住
    Keyboard.press(key);
    delay(ms);
    Keyboard.release(key);
  }
}

void setup() {
  Keyboard.begin();          // 启动 USB HID 键盘
  Serial.begin(115200);      // USB-CDC 串口(同一根 USB 线)
  delay(1000);               // 等待主机枚举完成
}

void loop() {
  static String buf = "";
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n') {
      handleLine(buf);
      buf = "";
    } else if (c != '\r' && buf.length() < 64) {
      buf += c;
    }
  }
  delay(2);
}
