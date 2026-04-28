/**
 * copy-vad-models.js — 将 VAD + ONNX Runtime WASM 文件复制到 public/ 目录
 *
 * 目的：让 @ricky0123/vad-web 在离线环境下也能工作，无需从 CDN 下载模型。
 *
 * 运行时机：npm install（postinstall）或手动执行
 */

import fs from "fs";
import path from "path";

const FILES = [
  // VAD ONNX 模型
  { src: "node_modules/@ricky0123/vad-web/dist/silero_vad_legacy.onnx", dst: "public/silero_vad_legacy.onnx" },
  { src: "node_modules/@ricky0123/vad-web/dist/silero_vad_v5.onnx", dst: "public/silero_vad_v5.onnx" },
  // VAD AudioWorklet
  { src: "node_modules/@ricky0123/vad-web/dist/vad.worklet.bundle.min.js", dst: "public/vad.worklet.bundle.min.js" },
  // ONNX Runtime WASM（覆盖常见变体）
  { src: "node_modules/onnxruntime-web/dist/ort-wasm-simd-threaded.wasm", dst: "public/ort-wasm-simd-threaded.wasm" },
  { src: "node_modules/onnxruntime-web/dist/ort-wasm-simd.wasm", dst: "public/ort-wasm-simd.wasm" },
  { src: "node_modules/onnxruntime-web/dist/ort-wasm-threaded.wasm", dst: "public/ort-wasm-threaded.wasm" },
  { src: "node_modules/onnxruntime-web/dist/ort-wasm.wasm", dst: "public/ort-wasm.wasm" },
];

let copied = 0;
let skipped = 0;

for (const { src, dst } of FILES) {
  if (!fs.existsSync(src)) {
    console.warn(`[copy-vad-models] 源文件不存在，跳过: ${src}`);
    continue;
  }
  if (fs.existsSync(dst)) {
    const srcStat = fs.statSync(src);
    const dstStat = fs.statSync(dst);
    if (srcStat.size === dstStat.size && srcStat.mtimeMs <= dstStat.mtimeMs) {
      skipped++;
      continue;
    }
  }
  fs.copyFileSync(src, dst);
  copied++;
  console.log(`[copy-vad-models] 已复制: ${path.basename(dst)}`);
}

console.log(`[copy-vad-models] 完成 | 复制=${copied} 跳过=${skipped}`);
