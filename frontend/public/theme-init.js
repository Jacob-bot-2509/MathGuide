// 主题预加载:CSS 加载前就确定背景,避免开机闪白/闪黑。
// 独立文件是为了让部署 CSP 可以使用 script-src 'self',不必放开内联脚本。
try {
  var t = JSON.parse(localStorage.getItem('mg-settings') || '{}').theme === 'light' ? 'light' : 'dark'
  document.documentElement.dataset.theme = t
  document.documentElement.style.background = t === 'light' ? '#f6f5f0' : '#0b0e14'
} catch (e) {
  document.documentElement.style.background = '#0b0e14'
}
