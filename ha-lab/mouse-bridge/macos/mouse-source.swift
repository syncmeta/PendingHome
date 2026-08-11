// 读 macOS 上的鼠标事件，按行吐 JSON 到标准输出。喂给 ../bridge.py。
//
// 这是「平台适配器」那一层 —— 搬到 T630 时整个换成 linux/evdev-source.py，
// 控灯逻辑（logic.py）一行不用改。
//
// 编译：  ./build.sh        （产物 mouse-source，不进版本库）
// 列设备：./mouse-source --list
// 跑起来：./mouse-source --device 046d:c534 --device 1ea7:0064
//
// ⚠️ 首次运行会弹「输入监控」权限框 —— 因为要读鼠标的原始事件。
//    --list 不读事件，不会弹框。
//
// 关于 --seize：加了它被指定的鼠标就不再移动光标、点击也不会传给别的程序，
// 变成一个纯粹的遥控器。不加则鼠标照常用，同时事件也被我们读到（适合先试试水）。

import Foundation
import IOKit.hid

// HID 规范里的编号，见 USB HID Usage Tables
let kPageGenericDesktop: UInt32 = 0x01
let kPageButton: UInt32 = 0x09
let kUsageMouse: UInt32 = 0x02
let kUsageWheel: UInt32 = 0x38

let buttonNames: [UInt32: String] = [1: "left", 2: "right", 3: "middle"]

// 只上报这些设备（"厂商编号:型号编号"，小写十六进制）。空 = 全部上报。
var wantedDevices = Set<String>()
var seize = false
var listOnly = false

func parseArgs() {
    var it = CommandLine.arguments.dropFirst().makeIterator()
    while let arg = it.next() {
        switch arg {
        case "--list":
            listOnly = true
        case "--seize":
            seize = true
        case "--device":
            if let v = it.next() { wantedDevices.insert(v.lowercased()) }
        case "-h", "--help":
            print("""
            用法：
              mouse-source --list                    列出所有鼠标及其设备标识
              mouse-source --device VID:PID [...]    只上报这些鼠标的事件
              mouse-source --seize                   独占鼠标（不再移动光标）
            """)
            exit(0)
        default:
            FileHandle.standardError.write("未知参数：\(arg)\n".data(using: .utf8)!)
            exit(2)
        }
    }
}

func deviceID(_ device: IOHIDDevice) -> String {
    func intProp(_ key: String) -> Int {
        (IOHIDDeviceGetProperty(device, key as CFString) as? Int) ?? 0
    }
    // 两个鼠标型号不同，所以 厂商:型号 唯一且稳定 —— 换 USB 口也不变。
    return String(format: "%04x:%04x", intProp(kIOHIDVendorIDKey), intProp(kIOHIDProductIDKey))
}

func deviceName(_ device: IOHIDDevice) -> String {
    (IOHIDDeviceGetProperty(device, kIOHIDProductKey as CFString) as? String) ?? "(无名)"
}

func emit(_ json: String) {
    print(json)
    fflush(stdout)   // 下游是管道，不刷就会攒着不发，按键像失灵一样
}

let inputCallback: IOHIDValueCallback = { _, _, _, value in
    let element = IOHIDValueGetElement(value)
    guard let device = IOHIDElementGetDevice(element) as IOHIDDevice? else { return }

    let id = deviceID(device)
    if !wantedDevices.isEmpty && !wantedDevices.contains(id) { return }

    let page = IOHIDElementGetUsagePage(element)
    let usage = IOHIDElementGetUsage(element)
    let v = IOHIDValueGetIntegerValue(value)

    if page == kPageButton, let name = buttonNames[usage] {
        // 按下 v=1，抬起 v=0。bridge 只认按下，抬起也照发让它自己判断。
        emit("""
        {"device":"\(id)","type":"button","button":"\(name)","action":"\(v == 1 ? "down" : "up")"}
        """)
    } else if page == kPageGenericDesktop && usage == kUsageWheel && v != 0 {
        emit("""
        {"device":"\(id)","type":"wheel","delta":\(v)}
        """)
    }
}

parseArgs()

let manager = IOHIDManagerCreate(kCFAllocatorDefault, IOOptionBits(kIOHIDOptionsTypeNone))
IOHIDManagerSetDeviceMatching(manager, [
    kIOHIDDeviceUsagePageKey: kPageGenericDesktop,
    kIOHIDDeviceUsageKey: kUsageMouse,
] as CFDictionary)

if listOnly {
    // 只枚举、不打开设备 —— 所以不会弹权限框。
    IOHIDManagerScheduleWithRunLoop(manager, CFRunLoopGetCurrent(), CFRunLoopMode.defaultMode.rawValue)
    let devices = (IOHIDManagerCopyDevices(manager) as? Set<IOHIDDevice>) ?? []
    if devices.isEmpty {
        print("没找到鼠标。")
    } else {
        print("设备标识      名称")
        for d in devices.sorted(by: { deviceID($0) < deviceID($1) }) {
            print("\(deviceID(d))   \(deviceName(d))")
        }
        print("\n把要用的那两个标识填进 config.json 的 mice 里。")
    }
    exit(0)
}

IOHIDManagerRegisterInputValueCallback(manager, inputCallback, nil)
IOHIDManagerScheduleWithRunLoop(manager, CFRunLoopGetCurrent(), CFRunLoopMode.defaultMode.rawValue)

let openOptions = seize ? IOOptionBits(kIOHIDOptionsTypeSeizeDevice) : IOOptionBits(kIOHIDOptionsTypeNone)
let result = IOHIDManagerOpen(manager, openOptions)
if result != kIOReturnSuccess {
    FileHandle.standardError.write("""
    打不开 HID 设备（错误码 \(String(format: "0x%08x", result))）。
    多半是「输入监控」权限没给：
      系统设置 → 隐私与安全性 → 输入监控 → 勾上跑这个程序的终端。
    改完权限要把终端完全退出再重开才生效。\n
    """.data(using: .utf8)!)
    exit(1)
}

FileHandle.standardError.write(
    "在读鼠标事件了\(seize ? "（独占模式：这些鼠标不再控制光标）" : "")，Ctrl-C 退出\n"
        .data(using: .utf8)!)
CFRunLoopRun()
