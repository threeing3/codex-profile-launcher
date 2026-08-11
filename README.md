# Codex Profiles

一个面向 Windows 的 Codex 账户多开启动器。

Codex 默认会复用同一套本地登录状态。Codex Profiles 为每个已保存账户创建独立的 `CODEX_HOME` 和 Chromium `user-data-dir`，让你可以在同一台电脑上同时使用多个 Codex 账户，而不会修改系统默认 Codex 的数据。

> 本项目只负责本地桌面账户配置和启动，不是 API Key 切换器，也不会自动完成账户登录。

## 功能

- **系统默认 Codex**：直接打开电脑上现有的 Codex 账户和聊天记录，不复制、不覆盖原有数据。
- **独立账户配置**：每个新账户使用独立的本地配置目录、登录状态和浏览器数据目录。
- **共享用户技能**：默认 Codex 与独立账户可以引用同一份用户技能，同时保持内置系统技能和插件状态彼此隔离。
- **默认浏览器设置入口**：点击“默认浏览器”按钮即可打开 Windows 默认应用设置，登录过程仍由用户手动完成。
- **原生 Windows 操作**：保留系统标题栏、最小化、最大化、关闭、拖动、缩放和键盘操作习惯。
- **苹果风格界面**：宽窗口使用左侧账户栏与右侧详情区；小窗口自动上下排列，避免详情内容被遮挡。
- **本地数据存储**：账户元数据使用 SQLite 保存在 `%LOCALAPPDATA%\CodexProfileLauncher`。
- **不保存敏感凭据**：启动器不会保存 API Key、Cookie、访问令牌或密码。

## 环境要求

- Windows 10 或 Windows 11
- Python 3.11 或更高版本（从源码运行或打包时需要）
- 已安装 Windows 版 Codex；当前支持 Microsoft Store/AppX 安装方式

## 从源码运行

```powershell
python app.py
```

启动器会在运行时检测 Codex 的安装位置，不会把带版本号的 `WindowsApps` 路径写死在代码中。

## 构建 EXE

构建脚本会创建独立的构建虚拟环境，并使用 PyInstaller（Python 打包为 Windows 可执行程序的工具）：

```powershell
.\build_exe.ps1
```

生成的目录版程序位于：

```text
dist-v0.10\CodexProfiles\CodexProfiles.exe
```

如果你希望生成可以双击安装的单文件安装包，请运行：

```powershell
.\build_release.ps1
```

脚本会先构建目录版程序，再使用 Inno Setup（Windows 安装包制作工具）生成：

```text
dist-v0.10\CodexProfiles-Setup-v0.10.0.exe
```

这个安装包支持选择安装目录、创建开始菜单和桌面快捷方式，卸载入口也会自动写入 Windows。构建目录和 EXE 输出目录会被 Git 忽略，正式发布时应将安装包作为 GitHub Release（版本发布页）附件。

## 下载与安装

打开项目的 [Releases](https://github.com/threeing3/codex-profile-launcher/releases) 页面，下载最新的 `CodexProfiles-Setup-*.exe`，双击后按向导完成安装即可。安装程序只安装启动器本身，Codex 账户配置仍保存在本机 `%LOCALAPPDATA%\CodexProfileLauncher`，不会上传到云端。

## 使用方法

1. 启动 `CodexProfiles.exe`。
2. 选择“系统默认 Codex”打开原有账户，或点击“新建账户”创建独立账户配置。
3. 新建账户时填写账户名称和 Provider 信息。Provider 配置只管理启动器拥有的模型和 Base URL 字段。
4. 选择账户后点击“打开隔离 Codex”。
5. 如果登录页面打开了错误的浏览器，点击“默认浏览器”，修改 Windows 默认浏览器后再继续登录。

## 共享技能

点击左侧“共享技能”进入管理页。首次启用时，启动器会扫描默认 Codex 和所有独立账户的用户技能，展示合并计划、版本冲突、疑似敏感文件以及受影响账户。只有确认预览后才会执行迁移。

- 中央共享库位于 `%LOCALAPPDATA%\CodexProfileLauncher\shared-skills`。
- 每个用户技能通过独立的 Windows 目录联接接入账户；不会联接整个 `skills` 根目录。
- `.system` 内置技能、插件缓存、登录状态、聊天记录和项目数据始终保持隔离。
- 同名同内容技能自动合并；同名不同内容技能必须由用户选择版本。
- 迁移前保留原目录，任何失败都会回滚；操作日志、备份和历史快照均保存在启动器数据目录。
- 解除账户或单个技能共享时，会保留当前内容的独立副本，不会删除技能。
- 涉及目录结构变化的操作要求先正常关闭受影响的 Codex 窗口。
- 首版仅支持本机 Windows 固定 NTFS 磁盘，不会静默降级为复制同步。

启动器不会创建云端工作区，也不会复制 Codex 聊天记录。项目目录由每个 Codex 窗口自行打开，账户隔离通过本地独立目录实现。

## 测试

```powershell
python -m unittest discover -s tests -v
```

测试覆盖账户存储、目录隔离、Provider 配置边界、系统默认 Codex 行为、Windows 默认浏览器设置，以及技能扫描、冲突、目录联接、快照与恢复。

## 项目结构

```text
app.py                 程序入口
build_exe.ps1          Windows EXE 构建脚本
build_release.ps1      EXE 与 Windows 安装包构建脚本
installer.iss          Inno Setup 安装包配置
launcher/              界面、账户模型、业务服务、存储和 Codex 启动逻辑
tests/                 契约测试
DEVELOPMENT_LOG.md     开发和验证日志
LICENSE                MIT 开源许可
```

## 隐私与安全

- 账户配置和隔离目录只保存在本地电脑。
- 从启动器列表移除账户时，只删除启动器数据库记录，账户数据目录会保留。
- 共享技能迁移会先生成预览；疑似包含凭据的技能默认禁止共享，必须明确确认才能继续。
- 技能备份和快照不会自动清理，避免未经确认删除本地文件。
- 不会覆盖系统默认 Codex 的原有数据。
- 不会上传账户信息、配置文件或聊天记录。

## 许可证

本项目使用 MIT License（开源许可协议），详情见 [LICENSE](LICENSE)。
