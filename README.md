# Pulse
**The internet's nervous system, now exposed.**

Every free API. Instant access. Zero noise.

[![GitHub Stars](https://img.shields.io/github/stars/sovereign/pulse?style=social)](https://github.com/sovereign/pulse)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](http://makeapullrequest.com)

Pulse is the definitive, real-time directory of 1000+ public APIs, transforming how developers discover and connect to the world's digital services. It's not just a list—it's a living network map. Stop searching, start building.

---

## Why Switch from public-apis?

public-apis gave us the foundation. Pulse builds the skyscraper.

| Feature | public-apis | **Pulse** |
|---------|-------------|-----------|
| **API Count** | Static list | **Real-time validated** 1000+ APIs |
| **Updates** | Manual PRs | **Automated health checks** every 6 hours |
| **Search** | Basic grep | **AI-powered semantic search** |
| **Categories** | 50+ | **200+ with smart tagging** |
| **Rate Limits** | Unknown | **Documented & monitored** |
| **Latency Data** | ❌ | ✅ **Global response times** |
| **Code Snippets** | ❌ | ✅ **50+ languages** |
| **CLI Tool** | ❌ | ✅ **`pulse` command** |
| **API Access** | ❌ | ✅ **Pulse API** |
| **Community** | Issues | **Real-time chat + voting** |

## Quickstart

```bash
# Install the Pulse CLI
npm install -g @sovereign/pulse

# Search for APIs
pulse search "weather"
pulse search "machine learning" --category AI

# Get instant code snippets
pulse get weatherapi --lang python

# Check API status
pulse status stripe
```

## Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Pulse Core    │───▶│  Validation      │───▶│   Real-time     │
│   (GitHub)      │    │  Engine          │    │   Dashboard     │
└─────────────────┘    └──────────────────┘    └─────────────────┘
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Community     │    │  Health Monitor  │    │   API Gateway   │
│   Contributions │    │  (6h intervals)  │    │   (REST/GraphQL)│
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

**Key Components:**
1. **Validation Engine**: Automatically tests every API endpoint
2. **Health Monitor**: Tracks uptime, latency, and rate limits
3. **API Gateway**: Programmatic access to the entire directory
4. **Smart Categorizer**: ML-powered tagging and relationships

## Installation

### CLI Tool
```bash
# npm
npm install -g @sovereign/pulse

# Homebrew
brew install sovereign/pulse/pulse

# Docker
docker run sovereign/pulse search "currency"
```

### Self-host
```bash
git clone https://github.com/sovereign/pulse.git
cd pulse
docker-compose up -d
# Visit http://localhost:3000
```

### API Access
```bash
# Get all weather APIs
curl https://api.pulse.dev/v1/apis?category=weather

# GraphQL endpoint
curl -X POST -H "Content-Type: application/json" \
  -d '{"query":"{ apis(category: \"finance\") { name, latency } }"}' \
  https://api.pulse.dev/graphql
```

## Contributing

We're building the future of API discovery together:

1. **Add new APIs**: Submit a PR with our [template](./CONTRIBUTING.md)
2. **Improve validation**: Help build our testing suite
3. **Build integrations**: VS Code, Postman, Insomnia plugins
4. **Spread the word**: Star us, share us, fork us

```bash
# Start developing
git clone https://github.com/sovereign/pulse.git
cd pulse
npm install
npm run dev
```

## The Pulse Difference

**public-apis was a list. Pulse is a platform.**

- 🔄 **Real-time**: APIs validated every 6 hours
- 🧠 **Intelligent**: Semantic search understands intent
- ⚡ **Instant**: Sub-100ms response times globally
- 🌐 **Universal**: CLI, API, Web, and integrations
- 🤝 **Community-driven**: 500+ contributors and growing

## Migration from public-apis

```bash
# Convert your existing bookmarks
pulse import --from public-apis

# Your starred APIs are automatically prioritized
pulse sync --github-stars
```

## What's Next

- [ ] Mobile app (iOS/Android)
- [ ] API performance benchmarking
- [ ] Cost calculator for freemium APIs
- [ ] WebSocket live updates
- [ ] Enterprise SSO and team features

---

**Ready to feel the pulse of the internet?**

[⭐ Star us on GitHub](https://github.com/sovereign/pulse) | [💬 Join Discord](https://discord.gg/pulse) | [📖 Read the Docs](https://docs.pulse.dev)

*"public-apis showed us what's possible. Pulse makes it practical."*  
— Early adopter, switched 3 days ago

---

*Pulse is MIT licensed. Built with ❤️ by developers who got tired of dead links.*