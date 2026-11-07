# 森投屏接收端

把手机视频投到 Windows 电脑上播。DLNA、AirPlay、IPTV 都收。

电视盒子干的事，电脑干一遍：手机 App 点投屏，选这台电脑，视频就在电脑上放。

## 能干啥

- DLNA / UPnP 接收：抖音、B 站、腾讯、爱奇艺、优酷里的「TV」按钮
- AirPlay 接收：iPhone、iPad 隔空播放
- IPTV：填 m3u8 直链、m3u 列表，或者 rtp:// / udp:// 组播地址
- 播放 m3u8、ts、mp4、mkv，能借系统装的 HEVC / 杜比视界扩展
- 画质增强（对比度、饱和度、锐度）、等响度、音轨切换、字幕
- 屏幕顶部一条悬浮长条（灵动岛），常驻前台、自动居中，窗口最小化/收进托盘也不消失，点一下把窗口叫回来
- 手机扫码传文件：手机浏览器扫二维码打开上传页，同 Wi-Fi 点对点直传（不经过任何服务器、不用外网），电脑顶部灵动岛实时显示文件名和进度，传完自动打开文件所在位置
- 开机自启，能选静默启动（只留托盘）
- 主题、背景图、开屏动画都能换
- 只跑一个实例，开第二个会自动收掉，点悬浮条把已开的那个拉回来
- 点「退出」彻底清场：本软件、播放器后端、上次卡死残留的实例及其子进程全部结束，不留后台、不占端口

## 运行环境

- Windows 10 1809 以上 / Windows 11，64 位
- 手机和电脑同一个局域网，路由器别开 AP 隔离

## 怎么装

**微软商店**：搜「森投屏助手接收端」。

**绿色版**：下载 `森投屏接收端.exe`，双击就跑。

**源码跑**：

```
pip install -r requirements.txt
python main.py
```

第一次跑手机搜不到，点「更多 - 一键修复网络」，UAC 点是，重启软件。

## 搜不到 / 没画面

按顺序试：

1. 手机和电脑是不是同一个网。一个走 5G 热点、一个走公司网，搜不到
2. 路由器开了「AP 隔离 / 客户端隔离」就关掉
3. 用 App 里那个「TV / 投屏」按钮，不是系统自带的「无线投屏」
4. 鸿蒙系统给那个 App「附近的设备」权限
5. 还不行，点「手机连通性自检」，手机浏览器能打开那个地址，说明网通，问题在 App 那边

华为下拉菜单的「无线投屏 / 多屏协同」是整屏镜像，走系统 Miracast，由 Windows 自带的「无线显示」接收。这个软件只帮你把设置入口打开，不重复实现华为私有协议。

## 找我

QQ：1218563952，备注「投屏」。

新 App 要适配，把 apk 发我，说一句哪里不对就行。

## 用了什么

这软件站在下面这些项目上，感谢它们：

- [PyQt6](https://www.riverbankcomputing.com/software/pyqt/)（Riverbank Computing）— Qt6 的 Python 绑定，整个界面靠它
- [Qt Multimedia](https://www.qt.io/)（The Qt Company）— 播放引擎
- [FFmpeg](https://ffmpeg.org/)（FFmpeg 团队）— Qt Multimedia 内置解码，支持 m3u8 / ts / mp4 / mkv
- [NumPy](https://numpy.org/)— 画质增强的数值计算
- [qrcode](https://github.com/lincolnloop/python-qrcode) + [Pillow](https://python-pillow.org/)— 手机连通性自检的二维码
- [pylnk3](https://github.com/strayge/pylnk3)— 生成 Windows 快捷方式
- [cryptography](https://cryptography.io/)（pyca）— AirPlay 配对的加密握手

## 许可

MIT，见 LICENSE。
