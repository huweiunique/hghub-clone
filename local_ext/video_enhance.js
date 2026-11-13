/* GPU 画质增强：算法取自 LNPANDY/HGhub-MacOS-iOS-Version，提交 7cbc84e。
 * PolyForm Noncommercial 1.0.0: https://polyformproject.org/licenses/noncommercial/1.0.0
 * Required Notice: Copyright (c) 2026 HGhub contributors (https://github.com/Minireel/HGhub)
 * 原始源码与适配边界见 docs/third-party/HGhub-Noncommercial.md。
 */
(function () {
'use strict';
if (window.HGEnhance) return;
const VERT_SRC = `#version 300 es
in vec2 aPos;
out vec2 vScreenUv;
void main() {
  gl_Position = vec4(aPos, 0.0, 1.0);
  vScreenUv = vec2(aPos.x * 0.5 + 0.5, 0.5 - aPos.y * 0.5);
}
`;

const FRAG_SRC = `#version 300 es
precision highp float;

uniform sampler2D uTex;
uniform vec2 uCanvasSize;
uniform vec2 uVideoSize;
uniform int uFit;
uniform int uMode;

in vec2 vScreenUv;
out vec4 fragColor;

float luma(vec3 c) {
  return dot(c, vec3(0.299, 0.587, 0.114));
}

vec3 sampleClamped(vec2 uv, vec2 halfTexel) {
  return texture(uTex, clamp(uv, halfTexel, 1.0 - halfTexel)).rgb;
}

// 档位 1：自然清透（对角等值线抗锯齿 + 严格零过冲温和 RCAS，真人短剧耐看无硬边）
vec3 runNatural(vec2 uv, vec2 texel) {
  vec2 ht = texel * 0.5;
  vec3 c  = sampleClamped(uv, ht);
  vec3 n  = sampleClamped(uv + vec2(0.0, -texel.y), ht);
  vec3 s  = sampleClamped(uv + vec2(0.0,  texel.y), ht);
  vec3 w  = sampleClamped(uv + vec2(-texel.x, 0.0), ht);
  vec3 e  = sampleClamped(uv + vec2( texel.x, 0.0), ht);
  vec3 nw = sampleClamped(uv + vec2(-texel.x, -texel.y), ht);
  vec3 ne = sampleClamped(uv + vec2( texel.x, -texel.y), ht);
  vec3 sw = sampleClamped(uv + vec2(-texel.x,  texel.y), ht);
  vec3 se = sampleClamped(uv + vec2( texel.x,  texel.y), ht);

  float d1 = abs(luma(nw) - luma(se));
  float d2 = abs(luma(ne) - luma(sw));
  vec3 diagDir = d1 < d2 ? (nw + se) * 0.5 : (ne + sw) * 0.5;
  vec3 crossAvg = (n + s + w + e) * 0.25;
  vec3 edgeSmooth = mix(c, mix(crossAvg, diagDir, 0.45), 0.20);

  float lc = luma(c);
  float ln = luma(n), ls = luma(s), lw = luma(w), le = luma(e);
  float lMin = min(lc, min(min(ln, ls), min(lw, le)));
  float lMax = max(lc, max(max(ln, ls), max(lw, le)));
  float lRange = lMax - lMin;

  float gate = smoothstep(0.025, 0.088, lRange);
  float amp = clamp(min(lMin, 1.0 - lMax) / max(lMax, 1e-4), 0.0, 1.0);
  float wSharp = -0.14 * sqrt(amp) * gate;
  vec3 rcas = (c + (n + s + w + e) * wSharp) / max(1.0 + 4.0 * wSharp, 1e-4);
  vec3 sharp = rcas + (c - edgeSmooth) * (0.09 * gate);

  vec3 minC = min(c, min(min(n, s), min(w, e)));
  vec3 maxC = max(c, max(max(n, s), max(w, e)));
  vec3 clamped = clamp(sharp, minC, maxC);
  return mix(c, clamped, 0.76);
}

// 档位 2：影院质感（温和 RCAS + 局部通透微反差 Local Clarity + 去灰雾 S 曲线）
vec3 runCinema(vec2 uv, vec2 texel) {
  vec2 ht = texel * 0.5;
  vec3 c  = sampleClamped(uv, ht);
  vec3 n  = sampleClamped(uv + vec2(0.0, -texel.y), ht);
  vec3 s  = sampleClamped(uv + vec2(0.0,  texel.y), ht);
  vec3 w  = sampleClamped(uv + vec2(-texel.x, 0.0), ht);
  vec3 e  = sampleClamped(uv + vec2( texel.x, 0.0), ht);
  vec3 nw = sampleClamped(uv + vec2(-texel.x, -texel.y), ht);
  vec3 ne = sampleClamped(uv + vec2( texel.x, -texel.y), ht);
  vec3 sw = sampleClamped(uv + vec2(-texel.x,  texel.y), ht);
  vec3 se = sampleClamped(uv + vec2( texel.x,  texel.y), ht);

  float lc = luma(c);
  float ln = luma(n), ls = luma(s), lw = luma(w), le = luma(e);
  float lMin = min(lc, min(min(ln, ls), min(lw, le)));
  float lMax = max(lc, max(max(ln, ls), max(lw, le)));
  float lRange = lMax - lMin;

  float gate = smoothstep(0.020, 0.080, lRange);
  float amp = clamp(min(lMin, 1.0 - lMax) / max(lMax, 1e-4), 0.0, 1.0);
  float wSharp = -0.17 * sqrt(amp) * gate;
  vec3 rcas = (c + (n + s + w + e) * wSharp) / max(1.0 + 4.0 * wSharp, 1e-4);

  vec3 minC = min(c, min(min(n, s), min(w, e)));
  vec3 maxC = max(c, max(max(n, s), max(w, e)));
  vec3 rcasClamped = clamp(rcas, minC, maxC);

  // 局部立体微反差：仅在中高对比结构上增强前后景层次，暗部噪点区保持克制
  vec3 crossAvg = (n + s + w + e) * 0.25;
  vec3 diagAvg  = (nw + ne + sw + se) * 0.25;
  vec3 surround = crossAvg * 0.6 + diagAvg * 0.4;
  float clarityGate = smoothstep(0.018, 0.075, lRange);
  vec3 clarified = rcasClamped + (rcasClamped - surround) * (0.24 * clarityGate);

  vec3 min9 = min(minC, min(min(nw, ne), min(sw, se)));
  vec3 max9 = max(maxC, max(max(nw, ne), max(sw, se)));
  vec3 col = clamp(clarified, min9, max9);

  // 柔和胶片 S 曲线去低码率灰雾 + +5% 自然色彩净度
  col = mix(col, smoothstep(0.0, 1.0, col), 0.06);
  float outL = luma(col);
  return clamp(mix(vec3(outL), col, 1.05), 0.0, 1.0);
}

// 档位 3：超清锐利（高频适应 RCAS + 亚像素高频细节增强，适合模糊片源与小字）
vec3 runCrisp(vec2 uv, vec2 texel) {
  vec2 ht = texel * 0.5;
  vec3 c  = sampleClamped(uv, ht);
  vec3 n  = sampleClamped(uv + vec2(0.0, -texel.y), ht);
  vec3 s  = sampleClamped(uv + vec2(0.0,  texel.y), ht);
  vec3 w  = sampleClamped(uv + vec2(-texel.x, 0.0), ht);
  vec3 e  = sampleClamped(uv + vec2( texel.x, 0.0), ht);
  vec3 nw = sampleClamped(uv + vec2(-texel.x, -texel.y), ht);
  vec3 ne = sampleClamped(uv + vec2( texel.x, -texel.y), ht);
  vec3 sw = sampleClamped(uv + vec2(-texel.x,  texel.y), ht);
  vec3 se = sampleClamped(uv + vec2( texel.x,  texel.y), ht);

  float lc = luma(c);
  float ln = luma(n), ls = luma(s), lw = luma(w), le = luma(e);
  float lMin = min(lc, min(min(ln, ls), min(lw, le)));
  float lMax = max(lc, max(max(ln, ls), max(lw, le)));
  float lRange = lMax - lMin;

  float gate = smoothstep(0.016, 0.065, lRange);
  float amp = clamp(min(lMin, 1.0 - lMax) / max(lMax, 1e-4), 0.0, 1.0);
  float wSharp = -0.24 * sqrt(amp) * gate;
  vec3 rcas = (c + (n + s + w + e) * wSharp) / max(1.0 + 4.0 * wSharp, 1e-4);

  vec3 crossAvg = (n + s + w + e) * 0.25;
  vec3 sharp = rcas + (c - crossAvg) * (0.20 * gate);

  vec3 min9 = min(c, min(min(min(n, s), min(w, e)), min(min(nw, ne), min(sw, se))));
  vec3 max9 = max(c, max(max(max(n, s), max(w, e)), max(max(nw, ne), max(sw, se))));
  return clamp(sharp, min9 - 0.010 * gate, max9 + 0.010 * gate);
}

// 档位 4：漫剧锐线（零涂抹保纹理！不做双边磨皮，专注轮廓微收紧 + 发丝质感 RCAS 重塑）
vec3 runAnime3D(vec2 uv, vec2 texel) {
  vec2 ht = texel * 0.5;
  vec3 tl = sampleClamped(uv + vec2(-texel.x, -texel.y), ht);
  vec3 tc = sampleClamped(uv + vec2(0.0,      -texel.y), ht);
  vec3 tr = sampleClamped(uv + vec2( texel.x, -texel.y), ht);
  vec3 ml = sampleClamped(uv + vec2(-texel.x,  0.0), ht);
  vec3 mc = sampleClamped(uv, ht);
  vec3 mr = sampleClamped(uv + vec2( texel.x,  0.0), ht);
  vec3 bl = sampleClamped(uv + vec2(-texel.x,  texel.y), ht);
  vec3 bc = sampleClamped(uv + vec2(0.0,       texel.y), ht);
  vec3 br = sampleClamped(uv + vec2( texel.x,  texel.y), ht);

  float ltl = luma(tl), ltc = luma(tc), ltr = luma(tr);
  float lml = luma(ml), lmc = luma(mc), lmr = luma(mr);
  float lbl = luma(bl), lbc = luma(bc), lbr = luma(br);

  // 直接以原像素 mc 为基底：彻底杜绝 2.5D/AI 漫剧的塑料涂抹感
  float gx = (ltr + 2.0 * lmr + lbr) - (ltl + 2.0 * lml + lbl);
  float gy = (lbl + 2.0 * lbc + lbr) - (ltl + 2.0 * ltc + ltr);
  float gMag = length(vec2(gx, gy));
  vec2 dir = gMag > 1e-4 ? (vec2(gx, gy) / gMag) : vec2(0.0);

  // 仅对明确轮廓边做单跨度轻量收紧，发丝和肌肤细腻过渡完全不受平滑损伤
  float edgeMask = smoothstep(0.032, 0.145, gMag);
  vec3 pushed = mc;
  if (edgeMask > 0.01) {
    vec2 sNear = dir * (texel * 0.82);
    vec3 f1 = sampleClamped(uv + sNear, ht);
    vec3 b1 = sampleClamped(uv - sNear, ht);
    float lf1 = luma(f1), lb1 = luma(b1);
    vec3 darkSide = lf1 < lb1 ? f1 : b1;
    vec3 lightSide = lf1 > lb1 ? f1 : b1;
    float midL = 0.5 * (lf1 + lb1);
    vec3 target = (lmc < midL) ? darkSide : lightSide;
    pushed = mix(mc, target, 0.36 * edgeMask);
  }

  // 叠加 RCAS 精细纹理锐化，让发丝、服饰纹理与阴影边界同步变清晰
  float lMin = min(lmc, min(min(ltc, lbc), min(lml, lmr)));
  float lMax = max(lmc, max(max(ltc, lbc), max(lml, lmr)));
  float texGate = smoothstep(0.018, 0.070, lMax - lMin);
  float amp = clamp(min(lMin, 1.0 - lMax) / max(lMax, 1e-4), 0.0, 1.0);
  float wSharp = -0.18 * sqrt(amp) * texGate;
  vec3 rcas = (pushed + (tc + bc + ml + mr) * wSharp) / max(1.0 + 4.0 * wSharp, 1e-4);

  vec3 min9 = min(mc, min(min(min(tc, bc), min(ml, mr)), min(min(tl, tr), min(bl, br))));
  vec3 max9 = max(mc, max(max(max(tc, bc), max(ml, mr)), max(max(tl, tr), max(bl, br))));
  vec3 outC = clamp(rcas, min9, max9);

  // 轻微提升通透饱和度 (+5%)
  float outL = luma(outC);
  return clamp(mix(vec3(outL), outC, 1.05), 0.0, 1.0);
}

// 档位 5：二次元重绘（窄门限净底去蚊式噪点 + 双跨度 Anime4K 边缘重构 + 描边加固）
vec3 runAnime2D(vec2 uv, vec2 texel) {
  vec2 ht = texel * 0.5;
  vec3 tl = sampleClamped(uv + vec2(-texel.x, -texel.y), ht);
  vec3 tc = sampleClamped(uv + vec2(0.0,      -texel.y), ht);
  vec3 tr = sampleClamped(uv + vec2( texel.x, -texel.y), ht);
  vec3 ml = sampleClamped(uv + vec2(-texel.x,  0.0), ht);
  vec3 mc = sampleClamped(uv, ht);
  vec3 mr = sampleClamped(uv + vec2( texel.x,  0.0), ht);
  vec3 bl = sampleClamped(uv + vec2(-texel.x,  texel.y), ht);
  vec3 bc = sampleClamped(uv + vec2(0.0,       texel.y), ht);
  vec3 br = sampleClamped(uv + vec2( texel.x,  texel.y), ht);

  // 1. 窄门限颜色导向净底（系数 720.0：只清理极微小的平涂块压缩噪点，绝不糊掉精细阴影）
  vec3 bSum = mc;
  float wSum = 1.0;
  float w0 = exp(-dot(tl - mc, tl - mc) * 720.0); bSum += tl * w0; wSum += w0;
  float w1 = exp(-dot(tc - mc, tc - mc) * 720.0); bSum += tc * w1; wSum += w1;
  float w2 = exp(-dot(tr - mc, tr - mc) * 720.0); bSum += tr * w2; wSum += w2;
  float w3 = exp(-dot(ml - mc, ml - mc) * 720.0); bSum += ml * w3; wSum += w3;
  float w4 = exp(-dot(mr - mc, mr - mc) * 720.0); bSum += mr * w4; wSum += w4;
  float w5 = exp(-dot(bl - mc, bl - mc) * 720.0); bSum += bl * w5; wSum += w5;
  float w6 = exp(-dot(bc - mc, bc - mc) * 720.0); bSum += bc * w6; wSum += w6;
  float w7 = exp(-dot(br - mc, br - mc) * 720.0); bSum += br * w7; wSum += w7;
  vec3 celBase = bSum / wSum;

  float ltl = luma(tl), ltc = luma(tc), ltr = luma(tr);
  float lml = luma(ml), lmc = luma(mc), lmr = luma(mr);
  float lbl = luma(bl), lbc = luma(bc), lbr = luma(br);

  // 2. 双跨度 Sobel 梯度法线（0.80x + 1.30x）精准收窄 2D 线稿边界
  float gx = (ltr + 2.0 * lmr + lbr) - (ltl + 2.0 * lml + lbl);
  float gy = (lbl + 2.0 * lbc + lbr) - (ltl + 2.0 * ltc + ltr);
  float gMag = length(vec2(gx, gy));
  vec2 dir = gMag > 1e-4 ? (vec2(gx, gy) / gMag) : vec2(0.0);

  vec2 sNear = dir * (texel * 0.80);
  vec2 sFar  = dir * (texel * 1.30);
  vec3 f1 = sampleClamped(uv + sNear, ht);
  vec3 b1 = sampleClamped(uv - sNear, ht);
  vec3 f2 = sampleClamped(uv + sFar, ht);
  vec3 b2 = sampleClamped(uv - sFar, ht);
  float lf1 = luma(f1), lb1 = luma(b1);
  float lf2 = luma(f2), lb2 = luma(b2);

  vec3 fPeak = lf1 < lf2 ? f1 : f2;
  vec3 bPeak = lb1 < lb2 ? b1 : b2;
  vec3 fBright = lf1 > lf2 ? f1 : f2;
  vec3 bBright = lb1 > lb2 ? b1 : b2;

  float fMinL = min(lf1, lf2), bMinL = min(lb1, lb2);
  float fMaxL = max(lf1, lf2), bMaxL = max(lb1, lb2);
  vec3 darkSide = fMinL < bMinL ? fPeak : bPeak;
  vec3 lightSide = fMaxL > bMaxL ? fBright : bBright;

  float edgeMask = smoothstep(0.024, 0.135, gMag);
  vec3 pushed = celBase;
  if (edgeMask > 0.01) {
    float midL = 0.5 * (min(fMinL, bMinL) + max(fMaxL, bMaxL));
    vec3 target = (lmc < midL) ? darkSide : lightSide;
    pushed = mix(celBase, target, 0.52 * edgeMask);
  }

  // 3. 深色描边线芯适度压黑加固
  float avg8Luma = (ltl + ltc + ltr + lml + lmr + lbl + lbc + lbr) * 0.125;
  float lineDarkening = clamp((avg8Luma - lmc) * 0.36, 0.0, 0.05) * edgeMask;
  pushed *= (1.0 - lineDarkening);

  // 4. 极值保护反差锐化 + +8% 鲜明色彩补偿
  vec3 avg4 = (tc + bc + ml + mr) * 0.25;
  vec3 wideMin = min(mc, min(min(min(tc, bc), min(ml, mr)), min(min(f1, b1), min(f2, b2))));
  vec3 wideMax = max(mc, max(max(max(tc, bc), max(ml, mr)), max(max(f1, b1), max(f2, b2))));
  vec3 sharp = pushed + (pushed - avg4) * (0.45 * edgeMask);
  vec3 outC = clamp(sharp, wideMin, wideMax);

  outC = mix(outC, smoothstep(0.0, 1.0, outC), 0.05);
  float outL = luma(outC);
  return clamp(mix(vec3(outL), outC, 1.08), 0.0, 1.0);
}

void main() {
  float canvasAr = uCanvasSize.x / max(1.0, uCanvasSize.y);
  float videoAr = uVideoSize.x / max(1.0, uVideoSize.y);
  vec2 scale;
  if (uFit == 0) {
    // contain：超出视频区域直接填黑，保证宽高比与 <video object-contain> 像素对齐
    scale = canvasAr > videoAr ? vec2(canvasAr / videoAr, 1.0) : vec2(1.0, videoAr / canvasAr);
  } else {
    // cover：与 <video object-cover> 居中裁切对齐
    scale = canvasAr > videoAr ? vec2(1.0, videoAr / canvasAr) : vec2(canvasAr / videoAr, 1.0);
  }

  vec2 uv = (vScreenUv - 0.5) * scale + 0.5;
  if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) {
    fragColor = vec4(0.0, 0.0, 0.0, 1.0);
    return;
  }

  vec2 texel = 1.0 / max(uVideoSize, vec2(1.0));
  vec3 rgb;
  if (uMode == 2) rgb = runCinema(uv, texel);
  else if (uMode == 3) rgb = runCrisp(uv, texel);
  else if (uMode == 4) rgb = runAnime3D(uv, texel);
  else if (uMode == 5) rgb = runAnime2D(uv, texel);
  else rgb = runNatural(uv, texel);
  fragColor = vec4(rgb, 1.0);
}
`;

function compileShader(gl, type, source) {
  const s = gl.createShader(type);
  if (!s) return null;
  gl.shaderSource(s, source);
  gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
    gl.deleteShader(s);
    return null;
  }
  return s;
}

function initGl(canvas) {
  const gl = canvas.getContext("webgl2", {
    alpha: false,
    antialias: false,
    depth: false,
    stencil: false,
    premultipliedAlpha: false,
    preserveDrawingBuffer: false,
    powerPreference: "high-performance",
  });
  if (!gl) return null;

  const vs = compileShader(gl, gl.VERTEX_SHADER, VERT_SRC);
  const fs = compileShader(gl, gl.FRAGMENT_SHADER, FRAG_SRC);
  if (!vs || !fs) {
    if (vs) gl.deleteShader(vs);
    if (fs) gl.deleteShader(fs);
    return null;
  }

  const prog = gl.createProgram();
  if (!prog) {
    gl.deleteShader(vs);
    gl.deleteShader(fs);
    return null;
  }
  gl.attachShader(prog, vs);
  gl.attachShader(prog, fs);
  gl.linkProgram(prog);
  gl.deleteShader(vs);
  gl.deleteShader(fs);

  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
    gl.deleteProgram(prog);
    return null;
  }

  const vao = gl.createVertexArray();
  const vbo = gl.createBuffer();
  const tex = gl.createTexture();
  if (!vbo || !tex) {
    if (vao) gl.deleteVertexArray(vao);
    if (vbo) gl.deleteBuffer(vbo);
    if (tex) gl.deleteTexture(tex);
    gl.deleteProgram(prog);
    return null;
  }

  gl.bindVertexArray(vao);
  gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
  const aPos = gl.getAttribLocation(prog, "aPos");
  gl.enableVertexAttribArray(aPos);
  gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 0, 0);
  gl.bindVertexArray(null);

  gl.bindTexture(gl.TEXTURE_2D, tex);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);

  return {
    gl,
    prog,
    tex,
    vao,
    vbo,
    uTex: gl.getUniformLocation(prog, "uTex"),
    uCanvasSize: gl.getUniformLocation(prog, "uCanvasSize"),
    uVideoSize: gl.getUniformLocation(prog, "uVideoSize"),
    uFit: gl.getUniformLocation(prog, "uFit"),
    uMode: gl.getUniformLocation(prog, "uMode"),
  };
}


const SVG_DEFS = `<defs>
        <filter id="hg-sr-filter-natural" color-interpolation-filters="sRGB">
          <feConvolveMatrix
            order="3"
            kernelMatrix="0 -0.18 0 -0.18 1.72 -0.18 0 -0.18 0"
            preserveAlpha="true"
          />
        </filter>
        <filter id="hg-sr-filter-cinema" color-interpolation-filters="sRGB">
          <feConvolveMatrix
            order="3"
            kernelMatrix="-0.06 -0.22 -0.06 -0.22 2.12 -0.22 -0.06 -0.22 -0.06"
            preserveAlpha="true"
          />
          <feColorMatrix type="saturate" values="1.05" />
        </filter>
        <filter id="hg-sr-filter-crisp" color-interpolation-filters="sRGB">
          <feConvolveMatrix
            order="3"
            kernelMatrix="-0.12 -0.34 -0.12 -0.34 2.84 -0.34 -0.12 -0.34 -0.12"
            preserveAlpha="true"
          />
        </filter>
        <filter id="hg-sr-filter-anime_3d" color-interpolation-filters="sRGB">
          <feConvolveMatrix
            order="3"
            kernelMatrix="-0.08 -0.28 -0.08 -0.28 2.44 -0.28 -0.08 -0.28 -0.08"
            preserveAlpha="true"
          />
          <feColorMatrix type="saturate" values="1.05" />
        </filter>
        <filter id="hg-sr-filter-anime_2d" color-interpolation-filters="sRGB">
          <feConvolveMatrix
            order="3"
            kernelMatrix="-0.14 -0.40 -0.14 -0.40 3.16 -0.40 -0.14 -0.40 -0.14"
            preserveAlpha="true"
          />
          <feColorMatrix type="saturate" values="1.08" />
        </filter>
      </defs>`;

const presets = [
  ['natural', '自然清透', 1], ['cinema', '影院质感', 2], ['crisp', '超清锐利', 3],
  ['anime_3d', '漫剧锐线', 4], ['anime_2d', '二次元重绘', 5], ['off', '关闭增强', 0]
];
let mode = 'natural';
try { const saved = JSON.parse(localStorage.getItem('hg_sr_mode')); if (presets.some(p => p[0] === saved)) mode = saved; } catch (_) { /* 无设置时沿用来源默认自然档。 */ }
const defs = new DOMParser().parseFromString('<svg xmlns="http://www.w3.org/2000/svg">' + SVG_DEFS + '</svg>', 'image/svg+xml').documentElement;
defs.setAttribute('width', '0'); defs.setAttribute('height', '0'); defs.setAttribute('aria-hidden', 'true');
defs.style.cssText = 'position:absolute;pointer-events:none;opacity:0'; document.body.appendChild(defs);
const style = document.createElement('style');
style.textContent = '.hg-enhance-canvas{position:absolute;inset:0;width:100%;height:100%;z-index:1;pointer-events:none;opacity:0}.slide .acts .hg-sr-feed{font-size:11px;line-height:1.3;border-radius:10px}.slide .mutebtn{width:48px;height:48px;min-width:48px;min-height:48px;right:12px;top:12px}.slide .mutebtn svg{width:24px;height:24px}.hg-feed-choice{position:fixed;inset:10% 12px;z-index:2000;background:#17171ff5;color:#fff;padding:16px;overflow:auto;border:1px solid #aaa;border-radius:14px}.hg-feed-choice button{display:block;width:100%;min-height:44px;margin:8px 0;color:#fff;background:#292933;border:1px solid #777;border-radius:8px}.hg-feed-choice button[aria-checked=true]{border-color:#ffda64}';
style.textContent += '.slide .mutebtn{top:var(--hg-screen-top,24px);right:var(--hg-screen-right,20px)}';
document.head.appendChild(style);
let canvas = document.createElement('canvas'); canvas.className = 'hg-enhance-canvas'; canvas.setAttribute('aria-hidden', 'true');
let pipe = null, current = null, fallback = false, verified = false, blackFrames = 0;
let frameId = 0, frameKind = '', frameVideo = null, feedMenu = null;
let fallbackReason = '', sourceKey = '';
function trace(event, data) { if (window.HGControls) HGControls.log(event, data); }
function cancelFrame() {
  if (frameId) {
    if (frameKind === 'video' && frameVideo && frameVideo.cancelVideoFrameCallback) frameVideo.cancelVideoFrameCallback(frameId);
    else cancelAnimationFrame(frameId);
  }
  frameId = 0; frameVideo = null;
}
function clearSurface() {
  cancelFrame(); canvas.style.opacity = '0';
  if (current) current.style.filter = '';
}
function destroy() {
  clearSurface();
  if (pipe) { const {gl, prog, tex, vao, vbo} = pipe; gl.deleteTexture(tex); gl.deleteBuffer(vbo); if (vao) gl.deleteVertexArray(vao); gl.deleteProgram(prog); pipe = null; }
}
function useFallback(reason) {
  cancelFrame(); fallback = true; fallbackReason = reason; canvas.style.opacity = '0';
  if (current) current.style.filter = mode === 'off' ? '' : 'url(#hg-sr-filter-' + mode + ')';
  trace('enhance.fallback', { reason: reason, mode: mode }); updateButtons();
}
function resetSource() {
  clearSurface(); fallback = false; fallbackReason = ''; verified = false; blackFrames = 0;
  sourceKey = current ? current.currentSrc : '';
}
function attach(video) {
  if (current !== video) {
    clearSurface(); current = video; resetSource();
    if (video) video.parentNode.insertBefore(canvas, video.nextSibling); else canvas.remove();
  }
  refresh();
}
function eligible(video) {
  return video && video.isConnected && !document.hidden && video.getClientRects().length > 0;
}
function isFullPlayer() { const p = document.getElementById('player'), pane = document.getElementById('playerPane'); return p && pane && !p.hidden && !pane.hidden; }
function pickVideo() {
  if (isFullPlayer()) return document.getElementById('video');
  const candidates = Array.from(document.querySelectorAll('#feed video.bgvid')).filter(eligible);
  return candidates.find(v => !v.paused) || candidates.find(v => v.closest('.slide.active')) || null;
}
function sync() { attach(pickVideo()); }
function resize() {
  if (!current) return;
  const dpr = Math.min(window.devicePixelRatio || 1, 2.5);
  const w = Math.min(2560, Math.max(2, Math.round(current.clientWidth * dpr)));
  const h = Math.min(2560, Math.max(2, Math.round(current.clientHeight * dpr)));
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
}
const probe = new Uint8Array(4);
function draw() {
  if (!eligible(current) || mode === 'off' || fallback || current.readyState < 2 || !current.videoWidth) return;
  if (sourceKey !== current.currentSrc) resetSource();
  resize();
  if (!pipe) {
    try { pipe = initGl(canvas); } catch (_) { pipe = null; }
    if (!pipe) { useFallback('webgl2_unavailable'); return; }
  }
  const {gl, prog, tex, vao, uTex, uCanvasSize, uVideoSize, uFit, uMode} = pipe;
  try {
    gl.viewport(0, 0, canvas.width, canvas.height); gl.useProgram(prog); gl.bindVertexArray(vao);
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, current);
    gl.uniform1i(uTex, 0); gl.uniform2f(uCanvasSize, canvas.width, canvas.height);
    gl.uniform2f(uVideoSize, current.videoWidth, current.videoHeight);
    gl.uniform1i(uFit, getComputedStyle(current).objectFit === 'cover' ? 1 : 0);
    gl.uniform1i(uMode, presets.find(p => p[0] === mode)[2]);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4); gl.bindVertexArray(null);
    if (gl.getError() !== gl.NO_ERROR) { useFallback('webgl_draw_error'); return; }
    if (!verified) {
      for (const [x, y] of [[.5,.5],[.35,.38],[.65,.38],[.35,.62],[.65,.62]]) {
        gl.readPixels(Math.min(canvas.width - 1, Math.floor(canvas.width * x)), Math.min(canvas.height - 1, Math.floor(canvas.height * y)), 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, probe);
        if (probe[0] + probe[1] + probe[2] > 6) { verified = true; trace('enhance.ready', {mode: mode}); updateButtons(); break; }
      }
      if (!verified && !current.paused && ++blackFrames >= 8 && current.currentTime >= .45) { useFallback('black_texture'); return; }
    }
    canvas.style.opacity = verified ? '1' : '0';
  } catch (_) { useFallback('video_texture_unreadable'); }
}
function schedule() {
  if (frameId || fallback || mode === 'off' || !eligible(current) || current.paused) return;
  frameVideo = current;
  const callback = () => { frameId = 0; draw(); schedule(); };
  if (current.requestVideoFrameCallback) { frameKind = 'video'; frameId = current.requestVideoFrameCallback(callback); }
  else { frameKind = 'raf'; frameId = requestAnimationFrame(callback); }
}
function refresh() {
  cancelFrame();
  if (!current || mode === 'off' || !eligible(current)) { clearSurface(); updateButtons(); return; }
  if (fallback) current.style.filter = 'url(#hg-sr-filter-' + mode + ')';
  else { current.style.filter = ''; draw(); schedule(); }
  updateButtons();
}
canvas.addEventListener('webglcontextlost', event => { event.preventDefault(); pipe = null; useFallback('context_lost'); });
canvas.addEventListener('webglcontextrestored', () => { pipe = null; resetSource(); refresh(); });
new ResizeObserver(() => { if (current) { resize(); draw(); } }).observe(canvas);
function select(value) {
  if (!presets.some(p => p[0] === value)) return;
  mode = value; try { localStorage.setItem('hg_sr_mode', JSON.stringify(mode)); } catch (_) { /* 网站数据不可写时保持本次设置。 */ }
  refresh();
}
function updateButtons() {
  const label = presets.find(p => p[0] === mode)[1];
  document.querySelectorAll('[data-hg-enhance]').forEach(b => {
    const text = b.classList.contains('hg-sr-feed') ? '画质\n' + (mode === 'off' ? '原画' : label.slice(0,2)) : '增强 ' + label + (fallback && mode !== 'off' ? '（兼容）' : '');
    if (b.textContent !== text) b.textContent = text;
    b.title = mode === 'off' ? '画质增强已关闭' : label + (fallback ? '：兼容滤镜，非 GPU 超分' : '：GPU 画质增强');
    b.setAttribute('aria-label', '画质增强：' + label + (fallback && mode !== 'off' ? '，兼容滤镜' : ''));
  });
}
function closeFeedMenu() { if (feedMenu) { const trigger = feedMenu.trigger; feedMenu.remove(); feedMenu = null; if (trigger && trigger.isConnected) trigger.focus(); } }
function menu(trigger, full) {
  const choices = presets.map(p => ({value:p[0], label:p[1]}));
  if (full && window.HGControls) { HGControls.choose('画质增强', choices, mode, select, trigger); return; }
  closeFeedMenu();
  feedMenu = document.createElement('section'); feedMenu.trigger = trigger;
  feedMenu.className = 'hg-feed-choice'; feedMenu.setAttribute('role','dialog'); feedMenu.setAttribute('aria-modal','true'); feedMenu.setAttribute('aria-label','画质增强');
  const heading = document.createElement('h3'); heading.textContent = '画质增强'; feedMenu.appendChild(heading);
  const group = document.createElement('div'); group.setAttribute('role', 'radiogroup'); group.setAttribute('aria-label','画质增强'); feedMenu.appendChild(group);
  choices.forEach(c => { const b = document.createElement('button'); b.type = 'button'; b.textContent = c.label; b.setAttribute('role','radio'); b.setAttribute('aria-checked',String(mode === c.value)); b.onclick = () => { select(c.value); closeFeedMenu(); }; group.appendChild(b); });
  const back = document.createElement('button'); back.type='button'; back.textContent='返回播放'; back.onclick=closeFeedMenu; feedMenu.appendChild(back);
  feedMenu.addEventListener('keydown', e => {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeFeedMenu(); }
    if (e.key === 'Tab') { e.preventDefault(); const buttons = Array.from(feedMenu.querySelectorAll('button')); const i=buttons.indexOf(document.activeElement); buttons[(i+(e.shiftKey?-1:1)+buttons.length)%buttons.length].focus(); }
  });
  document.body.appendChild(feedMenu); feedMenu.querySelector('[aria-checked=true]').focus();
}
function addButton(parent, full) {
  if (!parent || parent.querySelector('[data-hg-enhance]')) return;
  const b = document.createElement('button'); b.type='button'; b.setAttribute('data-hg-enhance','');
  b.className=full ? 'btn ghost' : 'hg-sr-feed';
  b.onclick=e=>{e.stopPropagation();menu(b,full);};
  // 放在右侧操作栏首位，保留原有分享按钮的底部对齐关系。
  if (full) parent.appendChild(b); else parent.insertBefore(b,parent.firstChild);
  updateButtons();
}
function scan() { addButton(document.querySelector('#playerPane .ctl'),true); document.querySelectorAll('#feed .slide .acts').forEach(el=>addButton(el,false)); }
new MutationObserver(() => { scan(); sync(); }).observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['hidden']});
document.addEventListener('play', e => { if (e.target.matches && e.target.matches('#video,#feed video.bgvid')) sync(); },true);
['loadeddata','seeked','pause','emptied','loadstart'].forEach(name=>document.addEventListener(name,e=>{
  if (e.target !== current) return;
  if (name === 'loadstart' || name === 'emptied') resetSource();
  refresh();
},true));
document.addEventListener('visibilitychange',sync);
window.addEventListener('pagehide',()=>{destroy();current=null;canvas.remove();closeFeedMenu();});
window.addEventListener('pageshow',sync);
window.addEventListener('storage',e=>{if(e.key === 'hg_sr_mode'){try{const v=JSON.parse(e.newValue);if(presets.some(p=>p[0]===v)){mode=v;refresh();}}catch(_){}}});
window.HGEnhance={getMode:()=>mode,setMode:select,getState:()=>({mode:mode,fallback:fallback,reason:fallbackReason,ready:verified,active:!!current})};
scan();sync();
})();
