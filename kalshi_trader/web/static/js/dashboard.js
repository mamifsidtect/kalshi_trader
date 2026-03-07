// Shared dashboard utilities
function formatPnl(value) {
  const sign = value >= 0 ? '+' : '';
  return `${sign}$${value.toFixed(2)}`;
}
