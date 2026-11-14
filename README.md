# DaylightApp

原生 SwiftUI iOS + watchOS 应用，共享现有的 `SharedCore` 本地 Swift Package。
Phase 3A 提供 iPhone 上的计时、持久化记录、最近 7 天历史与每日目标设置。

## 模块

- `SharedCore`：保留 DaylightProgress，新增经校验的 Session、自然日汇总、可恢复的 Journal 和原子文件存储，以及 Swift Testing 测试。
- `iOSApp`：独立 `@main` 入口、iOS 17+ 今日计时、历史、补记和目标设置，MainActor 管理界面状态。
- `WatchApp`：独立 `@main` 入口、watchOS 10+ 进度界面和手动增加 5 分钟按钮。
- `project.yml`：XcodeGen 工程源，两个独立 application target 和共享 scheme，分别链接本地 `DaylightCore` product。
- `.github/workflows/build.yml`：SharedCore 测试、安装 XcodeGen、生成工程和两个 Simulator 构建。

`DailyDaylightSummary` 复用已核对的 DaylightProgress 公开 API 计算目标比例及剩余分钟。
默认目标为 30 分钟；精确时长以起止时间的秒数差计算，按日累计后向下取完整分钟计算比例。

iPhone 将已完成记录、进行中的起始时间和每日目标保存在 Application Support，
重新启动后恢复。跨日记录使用当前日历与时区切分，不需要午夜清空任何数据。
这些记录由用户主动声明，不是传感器测量的真实日光暴露。
WatchApp 保留第二阶段的独立内存演示模型，尚未实现持久化或设备同步。
Watch target 使用现代单 target watch-only 配置，不嵌入 iOS app；
两个 Simulator 构建不代表配对安装或同步已经实现。

## Windows 验证

在 PowerShell 中使用现有工具链，Codex 沙箱可能需要批准访问该安装目录：

```powershell
Set-Location SharedCore
& 'C:\Users\Administrator\AppData\Local\Programs\Swift\Toolchains\6.4.2+Asserts\usr\bin\swift.exe' build
& 'C:\Users\Administrator\AppData\Local\Programs\Swift\Toolchains\6.4.2+Asserts\usr\bin\swift.exe' test
```

Windows 仅验证 SharedCore，不编译 SwiftUI 或生成 Xcode 工程。

## macOS / GitHub Actions

保留现有 `swift-tools-version: 6.4`，因此需要 Swift 6.4 或更高的 Xcode 工具链。
Swift language mode 的 `SWIFT_VERSION: 6.0` 与 tools-version 是两个不同设置。

截至 2026-11-15，Apple 的版本表列出 Xcode 27.1 使用 Swift 6.4；
GitHub 的 `macos-26` 镜像仍使用 Xcode 26.x / Swift 6.3。
工作流采用标准规格的 **`xcode-27` macOS Runner**，并通过 job 内的
`DEVELOPER_DIR` 选择 `/Applications/Xcode_27.1.app/Contents/Developer`。
该镜像目前标记为 public preview，未来镜像变更可能需要更新此路径。
不会选择 `-large` / `-xlarge`，也不安装额外 Xcode 或修改 SharedCore 的 tools-version。

参考官方资料：

- [Apple Xcode / Swift 版本要求](https://developer.apple.com/xcode/system-requirements)
- [GitHub Runner 标签](https://github.com/actions/runner-images)
- [xcode-27 已安装软件](https://github.com/actions/runner-images/blob/main/images/macos/xcode-27-arm64-Readme.md)
- [XcodeGen 配置规范](https://github.com/yonaskolb/XcodeGen/blob/master/Docs/ProjectSpec.md)

工作流在 push、pull request 或手动 dispatch 时运行。先输出工具链版本、SDK，
解析包并运行 `swift test`，再执行 XcodeGen 和两个独立的 Simulator build。
Watch build 会在 iOS build 失败但工程生成成功时继续执行，分别保留真实日志。
两个构建均使用 `CODE_SIGNING_ALLOWED=NO`，不需要开发者会员、证书或 TestFlight。
未配置任何付费服务；请在仓库的免费 Actions 配额内使用，避免启用超额付费。

在已有兼容 Xcode 的 Mac 上也可以运行：

```bash
swift test --package-path SharedCore
brew install xcodegen
xcodegen generate --spec project.yml
xcodebuild -project DaylightApp.xcodeproj -scheme DaylightIOS -configuration Debug -sdk iphonesimulator -destination 'generic/platform=iOS Simulator' -derivedDataPath build/iOS CODE_SIGNING_ALLOWED=NO build
xcodebuild -project DaylightApp.xcodeproj -scheme DaylightWatch -configuration Debug -sdk watchsimulator -destination 'generic/platform=watchOS Simulator' -derivedDataPath build/watchOS CODE_SIGNING_ALLOWED=NO build
```

生成的 `DaylightApp.xcodeproj` 不提交，以 `project.yml` 为准。
Bundle ID 暂用 `org.example.daylight.ios` 和 `org.example.daylight.watch`。

## 验证边界

Windows 的包测试和配置静态检查不能证明 SwiftUI 已通过 Xcode 编译。
第二阶段的 macOS CI 已由项目维护者确认通过；Phase 3A 尚未运行新的远端构建。
本阶段仍需在 GitHub Actions 确认新增包代码和 iOS SwiftUI 代码的编译、链接及 app 打包。
未执行 push；未声称已完成本阶段的 Xcode 构建、Simulator 启动、界面实机、配对或同步验证。

详细数据规则、计时失败行为及手动验收步骤见 [Phase 3A 说明](docs/PHASE3A.md)。
