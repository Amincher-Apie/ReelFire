export function timeToTimelinePercent(time, duration) {
  const safeDuration = Number(duration);
  if (!Number.isFinite(safeDuration) || safeDuration <= 0) return 0;

  const safeTime = Number(time);
  if (!Number.isFinite(safeTime)) return 0;

  return Math.max(0, Math.min((safeTime / safeDuration) * 100, 100));
}

export function pointerXToTimelineTime(clientX, trackLeft, trackWidth, duration) {
  const safeWidth = Number(trackWidth);
  const safeDuration = Number(duration);
  if (
    !Number.isFinite(safeWidth)
    || safeWidth <= 0
    || !Number.isFinite(safeDuration)
    || safeDuration <= 0
  ) {
    return 0;
  }

  const pointerOffset = Number(clientX) - Number(trackLeft);
  const ratio = Math.max(0, Math.min(pointerOffset / safeWidth, 1));
  return ratio * safeDuration;
}
