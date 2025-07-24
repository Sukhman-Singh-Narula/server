# ESP32 Audio Streaming Server

A comprehensive, modular FastAPI server for managing ESP32 device connections with OpenAI Realtime API integration. This server handles real-time audio streaming, user management, learning progression, and system prompt management with robust security and monitoring features.

## 🎯 Features

### Core Functionality
- **🔐 Secure Device Authentication**: Device ID validation (ABCD1234 format)
- **🎵 Real-time Audio Streaming**: WebSocket connections for ESP32 ↔ OpenAI audio streaming
- **👥 User Management**: Registration, progress tracking, and session management
- **📚 Learning System**: Season/episode progression with customizable system prompts
- **🔥 Firebase Integration**: User data and prompt storage with Firestore
- **🛡️ Security Middleware**: Rate limiting, IP blocking, and request validation
- **📊 Monitoring**: Comprehensive logging and metrics collection

### Architecture Benefits
- **🏗️ Modular Design**: Clean separation of concerns for easy maintenance
- **🔄 Scalable**: Async/await throughout for high performance
- **🧪 Testable**: Dependency injection and service pattern
- **📝 Well-Documented**: Comprehensive API documentation and logging
- **🔒 Production-Ready**: Security middleware and error handling

## 📁 Project Structure

```
esp32_audio_server/
├── main.py                     # FastAPI app initialization
├── requirements.txt            # Dependencies
├── .env.example               # Environment variables template
├── README.md                  # This file
├── config/
│   ├── __init__.py
│   └── settings.py            # Configuration management
├── models/
│   ├── __init__.py
│   ├── user.py                # User data models
│   ├── system_prompt.py       # System prompt models
│   └── websocket.py           # WebSocket message models
├── services/
│   ├── __init__.py
│   ├── firebase_service.py    # Firebase operations
│   ├── openai_service.py      # OpenAI Realtime API
│   ├── websocket_service.py   # WebSocket management
│   ├── user_service.py        # User business logic
│   └── prompt_service.py      # System prompt logic
├── routes/
│   ├── __init__.py
│   ├── auth.py                # User registration
│   ├── users.py               # User management
│   ├── prompts.py             # System prompt management
│   └── websocket.py           # WebSocket endpoints
├── utils/
│   ├── __init__.py
│   ├── validators.py          # Validation functions
│   ├── logger.py              # Logging configuration
│   ├── security.py            # Security utilities
│   └── exceptions.py          # Custom exceptions
├── middleware/
│   ├── __init__.py
│   ├── security.py            # Security middleware
│   └── logging.py             # Request logging
└── tests/
    ├── __init__.py
    ├── test_routes.py
    ├── test_services.py
    └── test_utils.py
```

## 🚀 Quick Start

### Prerequisites

- Python 3.8+
- Firebase project with Firestore enabled
- OpenAI API key with Realtime API access

### Installation

1. **Clone and setup the project:**
```bash
git clone <repository-url>
cd esp32_audio_server
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

2. **Configure Firebase:**
   - Create a Firebase project at [console.firebase.google.com](https://console.firebase.google.com/)
   - Enable Firestore Database
   - Generate a service account key:
     - Go to Project Settings → Service Accounts
     - Click "Generate new private key"
     - Save the JSON file securely

3. **Setup environment variables:**
```bash
cp .env.example .env
# Edit .env with your configuration
```

4. **Required environment variables:**
```bash
# Firebase
FIREBASE_CREDENTIALS_PATH="path/to/your/serviceAccountKey.json"

# OpenAI
OPENAI_API_KEY="sk-your-openai-api-key-here"

# Server
HOST="0.0.0.0"
PORT=8000
```

5. **Run the server:**
```bash
python main.py
```

The server will be available at:
- **API Documentation**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health
- **WebSocket**: ws://localhost:8000/ws/{device_id}

## 📋 API Endpoints

### Authentication
- `POST /auth/register` - Register a new user
- `GET /auth/verify/{device_id}` - Verify device registration
- `POST /auth/validate-device-id` - Validate device ID format

### User Management
- `GET /users/{device_id}` - Get user information
- `GET /users/{device_id}/statistics` - Get user statistics
- `GET /users/{device_id}/session` - Get session information
- `GET /users/{device_id}/session-duration` - Get session duration
- `PUT /users/{device_id}/progress` - Update learning progress
- `POST /users/{device_id}/advance-episode` - Advance to next episode
- `DELETE /users/{device_id}` - Deactivate user account

### System Prompts
- `POST /prompts/` - Create system prompt
- `GET /prompts/{season}/{episode}` - Get specific prompt
- `GET /prompts/{season}` - Get season overview
- `GET /prompts/` - Get all seasons overview
- `POST /prompts/validate` - Validate prompt content
- `PUT /prompts/{season}/{episode}/metadata` - Update prompt metadata
- `DELETE /prompts/{season}/{episode}` - Deactivate prompt

### WebSocket
- `WS /ws/{device_id}` - ESP32 device connection
- `GET /ws/connections` - Get active connections
- `GET /ws/connection/{device_id}` - Get specific connection info
- `POST /ws/disconnect/{device_id}` - Manually disconnect device

### System
- `GET /` - Server status
- `GET /health` - Health check
- `GET /metrics` - Application metrics

## 🔧 ESP32 Integration

### Device ID Format
Device IDs must follow the format: **4 uppercase letters + 4 digits** (e.g., `ABCD1234`)

### WebSocket Connection Flow
1. ESP32 connects to `ws://server:8000/ws/ABCD1234`
2. Server validates device ID and user registration
3. Server retrieves current episode system prompt
4. Server establishes OpenAI Realtime API connection
5. Audio streaming begins (ESP32 ↔ Server ↔ OpenAI)
6. Episode completion triggers automatic progression



## 🛡️ Security Features

### Device Authentication
- Device ID format validation
- User registration requirement
- Session management and timeouts

### Rate Limiting
- Configurable request limits per IP
- Automatic IP blocking for violations
- Graduated penalty system

### Input Validation
- SQL injection prevention
- XSS protection
- File upload validation
- Request size limits

### Security Headers
- CORS configuration
- Content Security Policy
- XSS protection headers
- Frame options

## 📊 Monitoring & Logging

### Structured Logging
- JSON-formatted logs
- Multiple log levels and files
- Request/response logging
- Security event logging

### Metrics Collection
- Request counts and response times
- Error rates and status codes
- Active connection tracking
- Performance monitoring

### Health Checks
- Service dependency monitoring
- Database connection health
- WebSocket service status
- OpenAI API connectivity

## 🏗️ Development

### Running Tests
```bash
pytest tests/ -v --cov=.
```

### Code Formatting
```bash
black .
isort .
flake8 .
```

### Type Checking
```bash
mypy .
```

### Development Server
```bash
# Auto-reload on changes
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## 🚀 Production Deployment

### Environment Setup
1. Set `DEBUG=False` in environment
2. Use production-grade WSGI server:
```bash
gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker
```

3. Configure reverse proxy (nginx):
```nginx
server {
    listen 80;
    server_name your-domain.com;
    
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Database Considerations
- Use Firestore in production mode
- Set up proper backup strategies
- Monitor Firestore usage and costs
- Consider read/write optimizations

### Security Checklist
- [ ] Use HTTPS in production
- [ ] Update CORS origins to specific domains
- [ ] Rotate API keys regularly
- [ ] Set up monitoring and alerting
- [ ] Configure proper Firebase security rules
- [ ] Use environment-specific configuration

## 🔧 Configuration

### Environment Variables
All configuration is managed through environment variables. See `.env.example` for complete list.

### Key Settings
- `EPISODES_PER_SEASON`: Number of episodes per season (default: 7)
- `MAX_SEASONS`: Maximum number of seasons (default: 10)
- `SESSION_TIMEOUT_MINUTES`: WebSocket session timeout (default: 30)
- `RATE_LIMIT_REQUESTS`: Requests per time window (default: 100)
- `RATE_LIMIT_WINDOW_SECONDS`: Rate limit window (default: 60)

## 🐛 Troubleshooting

### Common Issues

**1. Firebase Connection Failed**
- Verify service account key path
- Check Firebase project permissions
- Ensure Firestore is enabled

**2. OpenAI Connection Failed**
- Verify API key is correct
- Check Realtime API access
- Monitor OpenAI usage limits

**3. WebSocket Connection Rejected**
- Verify device ID format (ABCD1234)
- Check user registration
- Ensure system prompts exist

**4. High Memory Usage**
- Monitor active connections
- Check log file sizes
- Review metrics collection

### Debug Mode
Enable debug mode for detailed error messages:
```bash
DEBUG=True python main.py
```

### Logs Location
- Main logs: `logs/esp32_server.log`
- Request logs: `logs/requests.log`
- Security logs: `logs/security.log`
- Audio session logs: `logs/audio_sessions.log`

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature-name`
3. Make your changes with tests
4. Format code: `black . && isort .`
5. Run tests: `pytest`
6. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 📞 Support

For issues, questions, or contributions:
- Create an issue on GitHub
- Review the API documentation at `/docs`
- Check logs for detailed error information

---

**Happy coding! 🚀**