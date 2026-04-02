/**
 * emotion.ts — 情绪标签解析工具
 *
 * 纯函数，无任何外部依赖。
 * 被 useWebSocket 消费，也可在其他需要解析情绪标签的地方直接 import。
 */

export const EMOTION_TAGS = [
    "happy", "sad", "angry", "shy", "surprised", "neutral", "sigh",
] as const;

export type EmotionTag = typeof EMOTION_TAGS[number];

// 精确匹配已知标签（不区分大小写）
const EMOTION_REGEX = /\[(happy|sad|angry|shy|surprised|neutral|sigh)\]/gi;
// 兜底：清除 LLM 可能造出的任何未知 [xxx] 标签
const UNKNOWN_TAG_REGEX = /\[[a-zA-Z]+\]/gi;

/**
 * 从 AI 回复中提取情绪标签，返回干净文本 + 情绪名称。
 * - 先剥离已知标签，再用兜底正则清除残留未知标签。
 * - 无情绪标签时 emotion 为 null。
 */
export function parseEmotion(text: string): { cleanText: string; emotion: EmotionTag | null } {
    const match = text.match(EMOTION_REGEX);
    const emotion = match
        ? (match[0].slice(1, -1).toLowerCase() as EmotionTag)
        : null;
    const cleanText = text
        .replace(EMOTION_REGEX, "")
        .replace(UNKNOWN_TAG_REGEX, "")
        .replace(/\s{2,}/g, " ")
        .trim();
    return { cleanText, emotion };
}