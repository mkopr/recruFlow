export function scoreBadgeColor(scorePercent: number): string {
  const clamped = Math.max(0, Math.min(100, scorePercent));
  const hue = (clamped / 100) * 120; // 0 = red, 60 = yellow, 120 = green
  return `hsl(${hue}, 70%, 42%)`;
}
