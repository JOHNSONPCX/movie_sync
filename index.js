const express = require('express');
const bodyParser = require('body-parser');

const app = express();
const port = 3000;

// Store IPs and playback states
let users = {};  // { ip: { time: 0, state: 'paused' or 'playing' } }

// Middleware
app.use(bodyParser.json());

// Endpoint to receive the user's IP and current state (time, play/pause)
app.post('/sync', (req, res) => {
    const { ip, time, state } = req.body;

    // Save the user's state
    users[ip] = { time, state };
    console.log(`Received state from ${ip}: ${state}, time: ${time}`);

    // Respond with the other user's state for synchronization
    const otherUsers = Object.keys(users).filter(userIp => userIp !== ip);
    if (otherUsers.length > 0) {
        const otherUserIp = otherUsers[0];  // Take the first other user
        const otherUserState = users[otherUserIp];
        res.json({ syncWith: otherUserIp, time: otherUserState.time, state: otherUserState.state });
    } else {
        res.json({ message: "No other users to sync with yet." });
    }
});

// Endpoint to clear data when a user disconnects
app.post('/disconnect', (req, res) => {
    const { ip } = req.body;
    delete users[ip];
    res.json({ message: `${ip} disconnected` });
});

// Start the server
app.listen(port, () => {
    console.log(`Server running on http://localhost:${port}`);
});
