const { createProxyMiddleware } = require('http-proxy-middleware');

module.exports = function(app) {
  const target = process.env.HOST === 'host.docker.internal'
    ? 'http://host.docker.internal:8080'
    : 'http://localhost:8080';

  app.use(
    '/api',
    createProxyMiddleware({
      target,
      changeOrigin: true,
    })
  );
};
