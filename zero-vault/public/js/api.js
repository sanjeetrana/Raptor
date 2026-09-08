class ApiClient {
  constructor(baseUrl = '/api') {
    this.baseUrl = baseUrl;
  }

  async request(endpoint, options = {}) {
    try {
      const response = await fetch(`${this.baseUrl}${endpoint}`, {
        headers: { 'Content-Type': 'application/json' },
        ...options
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || `API request failed (${response.status})`);
      }
      return data;
    } catch (err) {
      // Re-throw for callers to handle - DO NOT console.log sensitive data here
      throw err;
    }
  }

  async get(endpoint) {
    return this.request(endpoint, { method: 'GET' });
  }

  async post(endpoint, body) {
    return this.request(endpoint, {
      method: 'POST',
      body: JSON.stringify(body)
    });
  }

  async put(endpoint, body) {
    return this.request(endpoint, {
      method: 'PUT',
      body: JSON.stringify(body)
    });
  }

  async delete(endpoint) {
    return this.request(endpoint, { method: 'DELETE' });
  }
}

window.api = new ApiClient();
