# HGhub 画质增强代码来源

`local_ext/video_enhance.js` 中的 GLSL 着色器、WebGL 初始化及 SVG 降级滤镜取自
LNPANDY/HGhub-MacOS-iOS-Version 的 `src/components/SuperResCanvas.tsx`，
提交 `7cbc84ebe4c468fea1c51a9aabcdf27a94c5301f`。

来源：<https://github.com/LNPANDY/HGhub-MacOS-iOS-Version>

网页端移植将 React 生命周期和菜单改为原生 JavaScript，共享单个渲染上下文，
保留五档增强算法及默认自然档。锁屏、长按和媒体恢复也参考该仓库的交互设计。

上述移植部分遵循 PolyForm Noncommercial License 1.0.0：
<https://polyformproject.org/licenses/noncommercial/1.0.0>

Required Notice: Copyright (c) 2026 HGhub contributors (https://github.com/Minireel/HGhub)

再分发时须一并保留条款或条款链接及上述 Required Notice；该部分仅按非商业用途授权。
