# DaylightApp

原生 SwiftUI iOS + watchOS 基础应用，共享现有的 `SharedCore` 本地 Swift Package。

## 模块

- `SharedCore`：现有 DaylightCore 业务模型及 Swift Testing 测试，保持不变。
- `iOSApp`：独立 `@main` 入口、iOS 17+ 进度界面和手动增加 5 分钟按钮。
- `WatchApp`：独立 `@main` 入口、watchOS 10+ 进度界面和手动增加 5 分钟按钮。
- `project.yml`：XcodeGen 工程源，两个独立 application target 和共享 scheme，分别链接本地 `DaylightCore` product。
- `.github/workflows/build.yml`：SharedCore 测试、安装 XcodeGen、生成工程和两个 Simulator 构建。

界面调用已核对的 `DaylightProgress()`、`outdoorMinutes`、`goalMinutes`、
`completionRatio`、`remainingMinutes`、`recordOutdoorMinutes(_:)`。
默认目标为 30 分钟，进度计算与边界处理均由 SharedCore 提供。

本阶段每个界面使用独立的 `@State` 内存模型；重新启动后恢复为零。
尚未实现持久化、跨日归档/自动重置、后台计时、自动户外检测或设备同步。
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
首次 GitHub Actions 运行仍需确认：Runner/工具链可用、包在 macOS 上的测试、
XcodeGen 生成结果、两个平台的 SwiftUI 类型检查、链接和 app 打包。
本阶段不声称已完成 Simulator 启动、界面实机验证、配对安装或同步验证。
