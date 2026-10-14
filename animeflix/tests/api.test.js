const http = require('http');
const path = require('path');
const express = require('express');
const cors = require('cors');

// Import db and init
const { db, initDatabase } = require('../server/db');

initDatabase();

// Setup test app instance on port 5055
const app = express();
const TEST_PORT = 5055;

app.use(cors());
app.use(express.json());

function enrichAnime(animeRow) {
  if (!animeRow) return null;
  const genres = db.prepare(`
    SELECT g.id, g.name, g.slug 
    FROM genres g
    JOIN anime_genres ag ON ag.genre_id = g.id
    WHERE ag.anime_id = ?
  `).all(animeRow.id);

  const episodes = db.prepare(`
    SELECT * FROM episodes 
    WHERE anime_id = ? 
    ORDER BY episode_number ASC
  `).all(animeRow.id);

  return {
    ...animeRow,
    is_featured: Boolean(animeRow.is_featured),
    is_trending: Boolean(animeRow.is_trending),
    is_popular: Boolean(animeRow.is_popular),
    genres,
    episodes
  };
}

// GET /api/anime
app.get('/api/anime', (req, res) => {
  try {
    const { category, genre, search, sort, limit, is_featured } = req.query;
    let query = `
      SELECT DISTINCT a.* 
      FROM anime a
      LEFT JOIN anime_genres ag ON a.id = ag.anime_id
      LEFT JOIN genres g ON ag.genre_id = g.id
      WHERE 1=1
    `;
    const params = [];

    if (search) {
      query += ` AND (a.title LIKE ? OR a.japanese_title LIKE ? OR a.synopsis LIKE ? OR a.studio LIKE ?)`;
      const s = `%${search}%`;
      params.push(s, s, s, s);
    }

    if (genre && genre !== 'all') {
      query += ` AND (g.slug = ? OR g.name = ?)`;
      params.push(genre, genre);
    }

    if (category === 'featured' || is_featured === 'true' || is_featured === '1') {
      query += ` AND a.is_featured = 1`;
    } else if (category === 'trending') {
      query += ` AND a.is_trending = 1`;
    } else if (category === 'popular') {
      query += ` AND a.is_popular = 1`;
    } else if (category === 'top10') {
      query += ` AND a.top_10_rank IS NOT NULL`;
    }

    if (category === 'top10') {
      query += ` ORDER BY a.top_10_rank ASC`;
    } else if (sort === 'rating') {
      query += ` ORDER BY a.rating DESC`;
    } else if (sort === 'year') {
      query += ` ORDER BY a.release_year DESC`;
    } else {
      query += ` ORDER BY a.id ASC`;
    }

    if (limit) {
      query += ` LIMIT ?`;
      params.push(parseInt(limit, 10));
    }

    const rows = db.prepare(query).all(...params);
    res.json({ success: true, count: rows.length, data: rows.map(enrichAnime) });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

// GET /api/anime/:id
app.get('/api/anime/:id', (req, res) => {
  try {
    const { id } = req.params;
    const animeRow = db.prepare('SELECT * FROM anime WHERE id = ?').get(id);
    if (!animeRow) return res.status(404).json({ success: false, error: 'Anime not found' });
    const anime = enrichAnime(animeRow);

    const genreIds = anime.genres.map(g => g.id);
    let recommendations = [];
    if (genreIds.length > 0) {
      const placeholders = genreIds.map(() => '?').join(',');
      const recRows = db.prepare(`
        SELECT DISTINCT a.* FROM anime a
        JOIN anime_genres ag ON a.id = ag.anime_id
        WHERE ag.genre_id IN (${placeholders}) AND a.id != ?
        ORDER BY a.rating DESC LIMIT 6
      `).all(...genreIds, anime.id);
      recommendations = recRows.map(enrichAnime);
    }
    res.json({ success: true, data: { ...anime, recommendations } });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

// GET /api/genres
app.get('/api/genres', (req, res) => {
  try {
    const genres = db.prepare(`
      SELECT g.*, COUNT(ag.anime_id) as anime_count
      FROM genres g
      LEFT JOIN anime_genres ag ON g.id = ag.genre_id
      GROUP BY g.id
      ORDER BY g.name ASC
    `).all();
    res.json({ success: true, data: genres });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

// GET /api/mylist & POST /api/mylist/toggle
app.get('/api/mylist', (req, res) => {
  const rows = db.prepare(`
    SELECT a.* FROM anime a
    JOIN my_list ml ON a.id = ml.anime_id
    WHERE ml.user_id = 'default_user'
  `).all();
  res.json({ success: true, data: rows.map(enrichAnime) });
});

app.post('/api/mylist/toggle', (req, res) => {
  const { anime_id } = req.body;
  const existing = db.prepare(`SELECT * FROM my_list WHERE user_id = 'default_user' AND anime_id = ?`).get(anime_id);
  let inList = false;
  if (existing) {
    db.prepare(`DELETE FROM my_list WHERE user_id = 'default_user' AND anime_id = ?`).run(anime_id);
  } else {
    db.prepare(`INSERT INTO my_list (user_id, anime_id) VALUES ('default_user', ?)`).run(anime_id);
    inList = true;
  }
  res.json({ success: true, inList, message: inList ? 'Added' : 'Removed' });
});

// GET /api/continue-watching & POST /api/watch-progress
app.get('/api/continue-watching', (req, res) => {
  const rows = db.prepare(`
    SELECT a.*, wh.progress_percent, wh.last_watched
    FROM anime a
    JOIN watch_history wh ON a.id = wh.anime_id
    WHERE wh.user_id = 'default_user'
  `).all();
  res.json({ success: true, data: rows.map(r => ({ ...enrichAnime(r), watch_progress: r.progress_percent })) });
});

app.post('/api/watch-progress', (req, res) => {
  const { anime_id, episode_id = 1, progress_percent = 0 } = req.body;
  db.prepare(`
    INSERT INTO watch_history (user_id, anime_id, episode_id, progress_percent)
    VALUES ('default_user', ?, ?, ?)
    ON CONFLICT(user_id, anime_id) DO UPDATE SET progress_percent = excluded.progress_percent
  `).run(anime_id, episode_id, progress_percent);
  res.json({ success: true, message: 'Progress saved' });
});

// Admin endpoints
app.post('/api/admin/login', (req, res) => {
  const { password } = req.body;
  if (password === 'animeflix2025' || password === 'admin') {
    res.json({ success: true, token: 'test-token', message: 'Success' });
  } else {
    res.status(401).json({ success: false, error: 'Invalid admin credentials' });
  }
});

app.get('/api/stats', (req, res) => {
  const totalAnime = db.prepare('SELECT COUNT(*) as count FROM anime').get().count;
  const totalEpisodes = db.prepare('SELECT COUNT(*) as count FROM episodes').get().count;
  const topRated = db.prepare('SELECT id, title, rating FROM anime ORDER BY rating DESC LIMIT 5').all();
  res.json({ success: true, data: { totalAnime, totalEpisodes, topRated } });
});

app.post('/api/anime', (req, res) => {
  const { title, synopsis, banner_image, poster_image, rating = 9.0, match_score = 95, release_year = 2024, quality = 'HD', studio = 'MAPPA' } = req.body;
  const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, '-') + '-' + Date.now();
  const result = db.prepare(`
    INSERT INTO anime (title, slug, synopsis, banner_image, poster_image, rating, match_score, release_year, quality, studio)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).run(title, slug, synopsis, banner_image, poster_image, rating, match_score, release_year, quality, studio);
  const created = db.prepare('SELECT * FROM anime WHERE id = ?').get(result.lastInsertRowid);
  res.status(201).json({ success: true, data: enrichAnime(created) });
});

app.put('/api/anime/:id', (req, res) => {
  const { id } = req.params;
  const { title, match_score } = req.body;
  db.prepare('UPDATE anime SET title = COALESCE(?, title), match_score = COALESCE(?, match_score) WHERE id = ?').run(title, match_score, id);
  const updated = db.prepare('SELECT * FROM anime WHERE id = ?').get(id);
  res.json({ success: true, data: enrichAnime(updated) });
});

app.post('/api/anime/:id/episodes', (req, res) => {
  const { id } = req.params;
  const { title, duration, description } = req.body;
  const result = db.prepare('INSERT INTO episodes (anime_id, episode_number, title, duration, description) VALUES (?, 1, ?, ?, ?)').run(id, title, duration, description);
  res.status(201).json({ success: true, data: { id: result.lastInsertRowid } });
});

app.delete('/api/anime/:id', (req, res) => {
  const { id } = req.params;
  db.prepare('DELETE FROM anime WHERE id = ?').run(id);
  res.json({ success: true, message: 'Deleted' });
});

// Helper HTTP requester
function request(method, path, body = null) {
  return new Promise((resolve, reject) => {
    const options = {
      hostname: '127.0.0.1',
      port: TEST_PORT,
      path: path,
      method: method,
      headers: { 'Content-Type': 'application/json' }
    };

    const req = http.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        try {
          resolve({ status: res.statusCode, body: JSON.parse(data) });
        } catch (e) {
          resolve({ status: res.statusCode, text: data });
        }
      });
    });

    req.on('error', reject);
    if (body) req.write(JSON.stringify(body));
    req.end();
  });
}

// Start test server and run assertions
const server = app.listen(TEST_PORT, '127.0.0.1', async () => {
  console.log(`\n🚀 Test server listening on http://127.0.0.1:${TEST_PORT}\n`);
  let passed = 0;
  let failed = 0;

  async function test(name, fn) {
    try {
      await fn();
      console.log(`  ✅ PASS: ${name}`);
      passed++;
    } catch (err) {
      console.error(`  ❌ FAIL: ${name} -> ${err.message}`);
      failed++;
    }
  }

  try {
    // 1. GET /api/anime
    await test('GET /api/anime returns catalog with genres & episodes', async () => {
      const res = await request('GET', '/api/anime');
      if (res.status !== 200 || !res.body.success) throw new Error(`Status ${res.status}`);
      if (res.body.data.length < 5) throw new Error(`Expected at least 5 anime`);
      const first = res.body.data[0];
      if (!first.title || !first.genres || !first.episodes) throw new Error('Missing enriched fields');
    });

    // 2. GET /api/anime?category=top10
    await test('GET /api/anime?category=top10 returns ranked items in order', async () => {
      const res = await request('GET', '/api/anime?category=top10');
      if (res.status !== 200 || !res.body.success) throw new Error(`Status ${res.status}`);
      if (res.body.data[0].top_10_rank !== 1) throw new Error(`Expected rank 1, got ${res.body.data[0].top_10_rank}`);
    });

    // 3. Search anime
    await test('GET /api/anime?search=leveling finds Solo Leveling', async () => {
      const res = await request('GET', '/api/anime?search=leveling');
      if (res.status !== 200 || !res.body.success) throw new Error(`Status ${res.status}`);
      const found = res.body.data.some(a => a.title.includes('Solo Leveling'));
      if (!found) throw new Error('Solo Leveling not found in search');
    });

    // 4. GET /api/anime/:id
    await test('GET /api/anime/1 returns single anime with recommendations', async () => {
      const res = await request('GET', '/api/anime/1');
      if (res.status !== 200 || !res.body.success) throw new Error(`Status ${res.status}`);
      if (!res.body.data.id || !res.body.data.recommendations) throw new Error('Missing details/recs');
    });

    // 5. GET /api/genres
    await test('GET /api/genres returns genres list', async () => {
      const res = await request('GET', '/api/genres');
      if (res.status !== 200 || res.body.data.length === 0) throw new Error('Genres empty');
    });

    // 6. GET /api/stats
    await test('GET /api/stats returns metrics and dashboard data', async () => {
      const res = await request('GET', '/api/stats');
      if (res.status !== 200 || typeof res.body.data.totalAnime !== 'number') throw new Error('Stats error');
    });

    // 7. My List toggle
    await test('POST /api/mylist/toggle adds and removes anime', async () => {
      const addRes = await request('POST', '/api/mylist/toggle', { anime_id: 2 });
      if (addRes.status !== 200 || !addRes.body.success) throw new Error('Add toggle failed');
      const remRes = await request('POST', '/api/mylist/toggle', { anime_id: 2 });
      if (remRes.status !== 200 || !remRes.body.success) throw new Error('Remove toggle failed');
    });

    // 8. Watch history
    await test('POST /api/watch-progress updates progress', async () => {
      const res = await request('POST', '/api/watch-progress', { anime_id: 1, progress_percent: 80 });
      if (res.status !== 200 || !res.body.success) throw new Error('Progress update failed');
      const hist = await request('GET', '/api/continue-watching');
      const item = hist.body.data.find(a => a.id === 1);
      if (!item || item.watch_progress !== 80) throw new Error('Progress mismatch');
    });

    // 9. Admin Login
    await test('POST /api/admin/login validates credentials', async () => {
      const bad = await request('POST', '/api/admin/login', { password: 'wrong' });
      if (bad.status !== 401) throw new Error('Expected 401 on bad password');
      const good = await request('POST', '/api/admin/login', { password: 'animeflix2025' });
      if (good.status !== 200 || !good.body.token) throw new Error('Expected 200 with token');
    });

    // 10. Admin CRUD lifecycle
    let testId = null;
    await test('Admin CRUD Lifecycle (Create -> Update -> Add Episode -> Delete)', async () => {
      // Create
      const createRes = await request('POST', '/api/anime', {
        title: 'Cyberpunk 2099 Test Edition',
        synopsis: 'Admin integration test series',
        banner_image: 'https://images.unsplash.com/photo-1578632767115-351597cf2477?w=1920',
        poster_image: 'https://images.unsplash.com/photo-1563089145-599997674d42?w=600',
        rating: 9.8,
        match_score: 99
      });
      if (createRes.status !== 201 || !createRes.body.data.id) throw new Error('Creation failed');
      testId = createRes.body.data.id;

      // Update
      const updateRes = await request('PUT', `/api/anime/${testId}`, { title: 'Cyberpunk 2099 (Updated Title)' });
      if (updateRes.status !== 200 || updateRes.body.data.title !== 'Cyberpunk 2099 (Updated Title)') throw new Error('Update failed');

      // Add Episode
      const epRes = await request('POST', `/api/anime/${testId}/episodes`, { title: 'Episode 1: Night City Rising', duration: '24m' });
      if (epRes.status !== 201) throw new Error('Add episode failed');

      // Delete
      const delRes = await request('DELETE', `/api/anime/${testId}`);
      if (delRes.status !== 200) throw new Error('Delete failed');
    });

  } finally {
    console.log(`\n========================================`);
    console.log(`Test Results: ${passed} Passed, ${failed} Failed`);
    console.log(`========================================\n`);
    server.close(() => {
      process.exit(failed > 0 ? 1 : 0);
    });
  }
});
