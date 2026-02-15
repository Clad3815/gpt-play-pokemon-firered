const WebSocket = require("ws");

const clients = new Set();

function broadcast(message) {
  const messageString = JSON.stringify(message);
  clients.forEach((client) => {
    if (client.readyState === WebSocket.OPEN) {
      client.send(messageString);
    }
  });
}

function registerClient(ws) {
  clients.add(ws);
}

function unregisterClient(ws) {
  clients.delete(ws);
}

module.exports = {
  WebSocket,
  clients,
  broadcast,
  registerClient,
  unregisterClient,
};

