# Enhanced ESP32 Audio Streaming Server - Complete Endpoint Summary

## 🏠 System Endpoints

### `GET /`
**Purpose**: Server status and feature overview  
**Returns**: Server information, version, available features, and endpoint listings  
**New**: Now includes enhanced features like daily limits and conversation tracking

### `GET /health`
**Purpose**: Comprehensive health check for all services  
**Returns**: Health status of Firebase, WebSocket, OpenAI, User Service, and Conversation Service  
**New**: Enhanced to include conversation service health monitoring

### `GET /metrics`
**Purpose**: Application performance metrics  
**Returns**: Request metrics, enhanced features status, service metrics, and active connection counts  
**New**: Includes conversation tracking and daily limits metrics

### `GET /features`
**Purpose**: Detailed information about enhanced features  
**Returns**: Complete feature documentation, endpoints, and usage workflows  
**New**: Documents daily limits and conversation transcription capabilities

---

## 🔐 Authentication Endpoints (`/auth`)

### `POST /auth/register`
**Purpose**: Register a new ESP32 device user  
**Input**: Device ID (ABCD1234 format), name, age  
**Returns**: User profile with initial daily usage tracking  
**Enhanced**: Now includes daily usage initialization

### `GET /auth/verify/{device_id}`
**Purpose**: Verify if device is registered  
**Returns**: Registration status, basic user info, current season/episode  
**Use Case**: Quick device validation without full user data

### `POST /auth/validate-device-id`
**Purpose**: Validate device ID format without checking registration  
**Input**: Device ID string  
**Returns**: Format validation result and requirements  
**Use Case**: Client-side validation before registration

### `GET /auth/registration-stats`
**Purpose**: Admin endpoint for registration statistics  
**Returns**: Placeholder for admin statistics  
**Note**: Requires admin authentication in production

---

## 👥 Enhanced User Management (`/users`)

### Core User Information

#### `GET /users/{device_id}`
**Purpose**: Get comprehensive user information  
**Returns**: User profile, learning progress, **daily usage statistics**  
**Enhanced**: Now includes episodes played today, remaining episodes, daily limits status

#### `GET /users/{device_id}/statistics`
**Purpose**: Comprehensive user statistics with daily usage  
**Returns**: Learning progress, time statistics, **daily/weekly/monthly usage patterns**  
**Enhanced**: Includes daily limits analysis and usage efficiency metrics

### Daily Limits Management (🆕 NEW)

#### `GET /users/{device_id}/daily-limits`
**Purpose**: Check current daily episode limits  
**Returns**: Episodes played today, remaining episodes, can play status, daily limit (3)  
**Use Case**: ESP32 client checks before starting episode

#### `GET /users/{device_id}/daily-usage`
**Purpose**: Get daily usage statistics for past N days  
**Input**: `days` parameter (1-30, default: 7)  
**Returns**: Daily episode counts, session times, efficiency scores  
**Use Case**: Analytics and usage pattern analysis

### Session Management

#### `GET /users/{device_id}/session`
**Purpose**: Get current session information with daily limits  
**Returns**: Connection status, duration, current position, **daily limits info**  
**Enhanced**: Now includes remaining episodes for the day

#### `GET /users/{device_id}/session-duration`
**Purpose**: Get current session duration  
**Returns**: Session duration in seconds and minutes, connection status

### Progress Management

#### `PUT /users/{device_id}/progress`
**Purpose**: Update learning progress (words/topics learned)  
**Input**: New words and topics lists  
**Returns**: Updated user profile  
**Note**: Does not affect daily limits or episode advancement

#### `POST /users/{device_id}/advance-episode`
**Purpose**: Manually advance to next episode (respects daily limits)  
**Returns**: Updated user profile or daily limit exceeded error (HTTP 429)  
**Enhanced**: **Enforces 3-episode daily limit**, automatic daily usage tracking

### User Management

#### `DELETE /users/{device_id}`
**Purpose**: Soft delete user account  
**Returns**: Deletion confirmation  
**Note**: Preserves conversation history and daily usage data

#### `GET /users/`
**Purpose**: Get all active connections (admin endpoint)  
**Returns**: Active connections with daily usage context

#### `GET /users/admin/daily-usage-summary`
**Purpose**: Admin endpoint for daily usage across all users  
**Returns**: Aggregated daily usage statistics  
**Note**: Requires admin authentication in production

---

## 📚 System Prompts (`/prompts`)

### Core Prompt Management

#### `POST /prompts/`
**Purpose**: Create or update system prompt  
**Input**: Season, episode, prompt content, type, metadata  
**Returns**: Created prompt information with version tracking

#### `GET /prompts/{season}/{episode}`
**Purpose**: Get system prompt metadata  
**Returns**: Prompt information without content (for listings)

#### `GET /prompts/{season}/{episode}/content`
**Purpose**: Get raw prompt content for OpenAI integration  
**Returns**: Full prompt text and character count  
**Use Case**: Internal server use for OpenAI connections

### Prompt Organization

#### `GET /prompts/{season}`
**Purpose**: Get overview of all episodes in a season  
**Returns**: Season completion statistics, available prompt types

#### `GET /prompts/`
**Purpose**: Get overview of all seasons  
**Returns**: Complete learning system overview with completion stats

### Prompt Utilities

#### `POST /prompts/validate`
**Purpose**: Validate prompt content and get improvement suggestions  
**Input**: Prompt text  
**Returns**: Validation results, errors, warnings, suggestions

#### `PUT /prompts/{season}/{episode}/metadata`
**Purpose**: Update prompt metadata without changing content  
**Input**: New metadata object  
**Returns**: Updated prompt information

#### `DELETE /prompts/{season}/{episode}`
**Purpose**: Deactivate prompt (soft delete)  
**Returns**: Deactivation confirmation

### Advanced Prompt Features

#### `POST /prompts/search`
**Purpose**: Search prompts by content, type, or season  
**Input**: Search criteria  
**Returns**: Matching prompts

#### `GET /prompts/{season}/{episode}/analytics`
**Purpose**: Get detailed analytics for specific prompt  
**Returns**: Usage statistics, content analysis, validation results

#### `GET /prompts/types`
**Purpose**: Get available prompt types  
**Returns**: List of supported prompt types with descriptions

---

## 🔌 WebSocket Connection (`/ws`)

### Core Connection

#### `WS /ws/{device_id}`
**Purpose**: ESP32 device real-time connection  
**Features**: 
- **Daily episode limit checking before connection**
- **Real-time conversation session tracking**
- Audio streaming (ESP32 ↔ OpenAI)
- Session management with automatic episode advancement
- **Daily usage time tracking**

### Connection Management

#### `GET /ws/connections`
**Purpose**: Get all active WebSocket connections  
**Returns**: Connection details with **conversation session info**  
**Enhanced**: Includes active conversation metadata

#### `GET /ws/connection/{device_id}`
**Purpose**: Get specific device connection information  
**Returns**: Connection status, duration, **conversation details**

#### `POST /ws/disconnect/{device_id}`
**Purpose**: Manually disconnect specific device  
**Returns**: Disconnection confirmation and session duration

#### `GET /ws/stats`
**Purpose**: WebSocket service statistics  
**Returns**: Connection metrics, **learning statistics**, active episodes

#### `GET /ws/health`
**Purpose**: WebSocket service health check  
**Returns**: Service dependencies health status

---

## 💬 Conversation Management (`/conversations`) - 🆕 NEW

### Core Conversation Access

#### `GET /conversations/{device_id}`
**Purpose**: Get user's conversation sessions list  
**Input**: `limit` parameter (1-500, default: 50)  
**Returns**: List of conversation summaries with metadata  
**Use Case**: Browse conversation history

#### `GET /conversations/{device_id}/session/{session_id}`
**Purpose**: Get complete conversation transcript  
**Returns**: Full session with all messages, timestamps, metadata  
**Use Case**: View detailed conversation history

#### `GET /conversations/{device_id}/active`
**Purpose**: Get currently active conversation session  
**Returns**: Real-time conversation stats, recent messages  
**Use Case**: Monitor ongoing conversation

### Conversation Search & Analytics

#### `POST /conversations/{device_id}/search`
**Purpose**: Search through conversation history  
**Input**: Search criteria (text, dates, message types, season/episode)  
**Returns**: Matching conversation sessions  
**Use Case**: Find specific conversations or topics

#### `GET /conversations/{device_id}/analytics`
**Purpose**: Comprehensive conversation analytics  
**Input**: `days` parameter (1-365, default: 30)  
**Returns**: Session counts, completion rates, message patterns, daily activity  
**Use Case**: Usage insights and learning progress analysis

#### `GET /conversations/{device_id}/season/{season}/episode/{episode}`
**Purpose**: Get all conversations for specific episode  
**Returns**: All conversation sessions for that episode  
**Use Case**: Episode-specific conversation review

### Conversation Export

#### `POST /conversations/{device_id}/export`
**Purpose**: Export conversation transcripts in multiple formats  
**Input**: Export configuration (format, filters, options)  
**Returns**: Exported data in JSON/CSV/TXT format  
**Formats**:
- **JSON**: Complete structured data with metadata
- **CSV**: Tabular format for analysis (downloadable file)
- **TXT**: Human-readable transcript (downloadable file)

### Admin Conversation Features

#### `GET /conversations/admin/stats`
**Purpose**: Global conversation statistics (admin)  
**Returns**: System-wide conversation metrics  
**Note**: Requires admin authentication

#### `DELETE /conversations/{device_id}/session/{session_id}`
**Purpose**: Delete specific conversation session  
**Returns**: Deletion confirmation  
**Note**: Soft delete with audit trail

---

## 🔄 Enhanced Workflow Integration

### Daily Limits Workflow
1. **Connection Check**: `WS /ws/{device_id}` validates daily limits before allowing connection
2. **Limit Monitoring**: `GET /users/{device_id}/daily-limits` shows current status
3. **Episode Advancement**: `POST /users/{device_id}/advance-episode` respects limits
4. **Usage Tracking**: All endpoints automatically track daily usage

### Conversation Tracking Workflow
1. **Session Start**: WebSocket connection automatically starts conversation session
2. **Real-time Capture**: All AI and user messages captured with timestamps
3. **Session End**: Conversation saved when WebSocket disconnects
4. **Analysis & Export**: Full conversation history available for analysis

### Key Integration Points
- **WebSocket ↔ Daily Limits**: Connection rejected if daily limit exceeded
- **WebSocket ↔ Conversations**: Automatic session tracking during connections
- **OpenAI ↔ Conversations**: Real-time transcription capture from OpenAI API
- **User Progress ↔ Daily Limits**: Episode advancement updates daily usage
- **Firebase**: All data (users, conversations, prompts) stored with enhanced schemas

### Error Handling
- **Daily Limit Exceeded**: HTTP 429 with retry information
- **Invalid Device ID**: HTTP 400 with format requirements
- **Session Not Found**: HTTP 404 with helpful error message
- **Export Failures**: Graceful degradation with partial data

This enhanced server provides a complete learning management system with robust daily usage controls and comprehensive conversation tracking for educational ESP32 applications.