// 兼容入口：改动前页面引用的是 dashboard-v2.js。
// 若浏览器还留着旧版 index.html 的副本，它会请求这个文件；这里按顺序补上
// 拆分后的三个文件，旧副本也能正常打开。新页面直接用三个分层文件，不经此文件。
document.write('<script src="dashboard-data.js?v=20261114a"><\/script>');
document.write('<script src="dashboard-metrics.js?v=20261114a"><\/script>');
document.write('<script src="dashboard-views.js?v=20261114a"><\/script>');
