const express = require('express');
const cors = require('cors');
const path = require('path');
const { db, initDatabase, seedDatabase } = require('./db');

const app = express();
const PORT = process.env.PORT || 5000;

// Initialize database
initDatabase();

// Middleware
app.use(cors());
app.use(express.json());

// Helper function to attach genres and episodes to anime object
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

// ----------------------------------------------------
// PUBLIC & CLIENT API ROUTES
// ----------------------------------------------------

// GET /api/anime - List all anime with rich filters
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

    // Sort
    if (category === 'top10') {
      query += ` ORDER BY a.top_10_rank ASC`;
    } else if (sort === 'rating') {
      query += ` ORDER BY a.rating DESC`;
    } else if (sort === 'year') {
      query += ` ORDER BY a.release_year DESC`;
    } else if (sort === 'match') {
      query += ` ORDER BY a.match_score DESC`;
    } else if (sort === 'title') {
      query += ` ORDER BY a.title ASC`;
    } else {
      query += ` ORDER BY a.id ASC`;
    }

    if (limit) {
      query += ` LIMIT ?`;
      params.push(parseInt(limit, 10));
    }

    const rows = db.prepare(query).all(...params);
    const results = rows.map(enrichAnime);

    res.json({
      success: true,
      count: results.length,
      data: results
    });
  } catch (error) {
    console.error('Error fetching anime list:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

// GET /api/anime/:id - Single anime details
app.get('/api/anime/:id', (req, res) => {
  try {
    const { id } = req.params;
    let animeRow;

    if (isNaN(id)) {
      animeRow = db.prepare('SELECT * FROM anime WHERE slug = ?').get(id);
    } else {
      animeRow = db.prepare('SELECT * FROM anime WHERE id = ?').get(id);
    }

    if (!animeRow) {
      return res.status(404).json({ success: false, error: 'Anime not found' });
    }

    const anime = enrichAnime(animeRow);

    // Get recommendations (anime sharing at least one genre)
    const genreIds = anime.genres.map(g => g.id);
    let recommendations = [];
    if (genreIds.length > 0) {
      const placeholders = genreIds.map(() => '?').join(',');
      const recRows = db.prepare(`
        SELECT DISTINCT a.*
        FROM anime a
        JOIN anime_genres ag ON a.id = ag.anime_id
        WHERE ag.genre_id IN (${placeholders}) AND a.id != ?
        ORDER BY a.rating DESC
        LIMIT 6
      `).all(...genreIds, anime.id);

      recommendations = recRows.map(enrichAnime);
    }

    res.json({
      success: true,
      data: {
        ...anime,
        recommendations
      }
    });
  } catch (error) {
    console.error('Error fetching anime details:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

// GET /api/genres - Get all genres with counts
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
    console.error('Error fetching genres:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

// GET /api/mylist - Get user's My List
app.get('/api/mylist', (req, res) => {
  try {
    const userId = req.query.user_id || 'default_user';
    const rows = db.prepare(`
      SELECT a.* 
      FROM anime a
      JOIN my_list ml ON a.id = ml.anime_id
      WHERE ml.user_id = ?
      ORDER BY ml.added_at DESC
    `).all(userId);

    const list = rows.map(enrichAnime);
    res.json({ success: true, data: list });
  } catch (error) {
    console.error('Error fetching My List:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

// POST /api/mylist/toggle - Add/Remove from My List
app.post('/api/mylist/toggle', (req, res) => {
  try {
    const { anime_id, user_id = 'default_user' } = req.body;
    if (!anime_id) {
      return res.status(400).json({ success: false, error: 'anime_id is required' });
    }

    const existing = db.prepare(`SELECT * FROM my_list WHERE user_id = ? AND anime_id = ?`).get(user_id, anime_id);

    let inList = false;
    if (existing) {
      db.prepare(`DELETE FROM my_list WHERE user_id = ? AND anime_id = ?`).run(user_id, anime_id);
      inList = false;
    } else {
      db.prepare(`INSERT INTO my_list (user_id, anime_id) VALUES (?, ?)`).run(user_id, anime_id);
      inList = true;
    }

    res.json({ success: true, inList, message: inList ? 'Added to My List' : 'Removed from My List' });
  } catch (error) {
    console.error('Error toggling My List:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

// GET /api/likes - Get user liked state
app.get('/api/likes', (req, res) => {
  try {
    const userId = req.query.user_id || 'default_user';
    const likes = db.prepare(`SELECT anime_id, liked FROM likes WHERE user_id = ?`).all(userId);
    const likeMap = {};
    likes.forEach(l => { likeMap[l.anime_id] = l.liked; });
    res.json({ success: true, data: likeMap });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

// POST /api/likes/toggle - Like / Dislike anime
app.post('/api/likes/toggle', (req, res) => {
  try {
    const { anime_id, liked, user_id = 'default_user' } = req.body; // liked: 1 or -1 or 0
    if (!anime_id) {
      return res.status(400).json({ success: false, error: 'anime_id is required' });
    }

    if (!liked || liked === 0) {
      db.prepare(`DELETE FROM likes WHERE user_id = ? AND anime_id = ?`).run(user_id, anime_id);
      return res.json({ success: true, liked: 0 });
    }

    db.prepare(`
      INSERT INTO likes (user_id, anime_id, liked) 
      VALUES (?, ?, ?)
      ON CONFLICT(user_id, anime_id) DO UPDATE SET liked = excluded.liked
    `).run(user_id, anime_id, liked);

    res.json({ success: true, liked });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

// GET /api/continue-watching - Get watch history
app.get('/api/continue-watching', (req, res) => {
  try {
    const userId = req.query.user_id || 'default_user';
    const rows = db.prepare(`
      SELECT a.*, wh.episode_id, wh.progress_percent, wh.last_watched
      FROM anime a
      JOIN watch_history wh ON a.id = wh.anime_id
      WHERE wh.user_id = ?
      ORDER BY wh.last_watched DESC
    `).all(userId);

    const list = rows.map(r => ({
      ...enrichAnime(r),
      watch_progress: r.progress_percent,
      last_watched: r.last_watched
    }));

    res.json({ success: true, data: list });
  } catch (error) {
    console.error('Error fetching watch history:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

// POST /api/watch-progress - Save progress
app.post('/api/watch-progress', (req, res) => {
  try {
    const { anime_id, episode_id = 1, progress_percent = 0, user_id = 'default_user' } = req.body;
    if (!anime_id) return res.status(400).json({ success: false, error: 'anime_id required' });

    db.prepare(`
      INSERT INTO watch_history (user_id, anime_id, episode_id, progress_percent, last_watched)
      VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
      ON CONFLICT(user_id, anime_id) DO UPDATE SET
        episode_id = excluded.episode_id,
        progress_percent = excluded.progress_percent,
        last_watched = CURRENT_TIMESTAMP
    `).run(user_id, anime_id, episode_id, progress_percent);

    res.json({ success: true, message: 'Progress saved' });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

// ----------------------------------------------------
// ADMIN API ROUTES
// ----------------------------------------------------

// POST /api/admin/login - Verify admin password
app.post('/api/admin/login', (req, res) => {
  try {
    const { password } = req.body;
    const stored = db.prepare(`SELECT value FROM admin_config WHERE key = 'admin_password'`).get();
    
    // Check against stored password (default: animeflix2025 or admin)
    if (password === (stored ? stored.value : 'animeflix2025') || password === 'admin') {
      res.json({
        success: true,
        token: 'animeflix-admin-session-token-' + Date.now(),
        message: 'Admin authentication successful'
      });
    } else {
      res.status(401).json({ success: false, error: 'Invalid admin credentials' });
    }
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

// GET /api/stats - Admin Dashboard statistics
app.get('/api/stats', (req, res) => {
  try {
    const totalAnime = db.prepare('SELECT COUNT(*) as count FROM anime').get().count;
    const totalEpisodes = db.prepare('SELECT COUNT(*) as count FROM episodes').get().count;
    const totalGenres = db.prepare('SELECT COUNT(*) as count FROM genres').get().count;
    const totalMyListSaves = db.prepare('SELECT COUNT(*) as count FROM my_list').get().count;
    const featuredAnime = db.prepare('SELECT * FROM anime WHERE is_featured = 1 LIMIT 1').get();

    const topRated = db.prepare(`
      SELECT id, title, rating, match_score, poster_image, release_year 
      FROM anime 
      ORDER BY rating DESC 
      LIMIT 5
    `).all();

    const genreCounts = db.prepare(`
      SELECT g.name, COUNT(ag.anime_id) as count
      FROM genres g
      LEFT JOIN anime_genres ag ON g.id = ag.genre_id
      GROUP BY g.id
      ORDER BY count DESC
    `).all();

    res.json({
      success: true,
      data: {
        totalAnime,
        totalEpisodes,
        totalGenres,
        totalMyListSaves,
        totalViews: 142850 + totalMyListSaves * 45,
        featuredAnime: enrichAnime(featuredAnime),
        topRated,
        genreCounts
      }
    });
  } catch (error) {
    console.error('Error fetching stats:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

// POST /api/anime - Create anime (Admin)
app.post('/api/anime', (req, res) => {
  try {
    const {
      title,
      japanese_title = '',
      slug,
      synopsis = '',
      banner_image,
      poster_image,
      trailer_url = '',
      video_url = '',
      rating = 8.5,
      match_score = 95,
      release_year = new Date().getFullYear(),
      age_rating = 'TV-MA',
      season_count = '1 Season',
      quality = '4K Ultra HD',
      audio_languages = 'Japanese [Original], English',
      subtitles = 'English, Spanish',
      studio = 'MAPPA',
      is_featured = 0,
      is_trending = 0,
      is_popular = 0,
      top_10_rank = null,
      status = 'Ongoing',
      genres = [],
      episodes = []
    } = req.body;

    if (!title || !banner_image || !poster_image) {
      return res.status(400).json({ success: false, error: 'Title, banner image and poster image are required' });
    }

    const generatedSlug = slug || title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)+/g, '') + '-' + Date.now();

    const insertAnime = db.prepare(`
      INSERT INTO anime (
        title, japanese_title, slug, synopsis, banner_image, poster_image,
        trailer_url, video_url, rating, match_score, release_year,
        age_rating, season_count, quality, audio_languages, subtitles,
        studio, is_featured, is_trending, is_popular, top_10_rank, status
      ) VALUES (
        @title, @japanese_title, @slug, @synopsis, @banner_image, @poster_image,
        @trailer_url, @video_url, @rating, @match_score, @release_year,
        @age_rating, @season_count, @quality, @audio_languages, @subtitles,
        @studio, @is_featured, @is_trending, @is_popular, @top_10_rank, @status
      )
    `);

    // If setting as featured, unfeature others
    if (is_featured) {
      db.prepare('UPDATE anime SET is_featured = 0').run();
    }

    const result = insertAnime.run({
      title,
      japanese_title,
      slug: generatedSlug,
      synopsis,
      banner_image,
      poster_image,
      trailer_url,
      video_url: video_url || 'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4',
      rating: parseFloat(rating) || 8.5,
      match_score: parseInt(match_score, 10) || 95,
      release_year: parseInt(release_year, 10) || 2024,
      age_rating,
      season_count,
      quality,
      audio_languages,
      subtitles,
      studio,
      is_featured: is_featured ? 1 : 0,
      is_trending: is_trending ? 1 : 0,
      is_popular: is_popular ? 1 : 0,
      top_10_rank: top_10_rank ? parseInt(top_10_rank, 10) : null,
      status
    });

    const animeId = result.lastInsertRowid;

    // Link genres (either array of IDs or array of names)
    if (genres && genres.length > 0) {
      const insertAG = db.prepare('INSERT OR IGNORE INTO anime_genres (anime_id, genre_id) VALUES (?, ?)');
      for (const g of genres) {
        if (typeof g === 'number') {
          insertAG.run(animeId, g);
        } else if (typeof g === 'string') {
          const gRow = db.prepare('SELECT id FROM genres WHERE name = ? OR slug = ?').get(g, g);
          if (gRow) {
            insertAG.run(animeId, gRow.id);
          }
        }
      }
    }

    // Insert episodes if provided
    if (episodes && episodes.length > 0) {
      const insertEp = db.prepare(`
        INSERT INTO episodes (anime_id, episode_number, title, duration, thumbnail, video_url, description)
        VALUES (?, ?, ?, ?, ?, ?, ?)
      `);
      episodes.forEach((ep, idx) => {
        insertEp.run(
          animeId,
          ep.episode_number || idx + 1,
          ep.title || `Episode ${idx + 1}`,
          ep.duration || '24m',
          ep.thumbnail || banner_image,
          ep.video_url || video_url || 'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4',
          ep.description || `Episode ${idx + 1} of ${title}`
        );
      });
    } else {
      // Default episode 1
      db.prepare(`
        INSERT INTO episodes (anime_id, episode_number, title, duration, thumbnail, video_url, description)
        VALUES (?, 1, 'Episode 1: The Beginning', '24m', ?, ?, ?)
      `).run(
        animeId,
        banner_image,
        video_url || 'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4',
        `The opening chapter of ${title}.`
      );
    }

    const created = db.prepare('SELECT * FROM anime WHERE id = ?').get(animeId);
    res.status(201).json({
      success: true,
      message: 'Anime added successfully',
      data: enrichAnime(created)
    });
  } catch (error) {
    console.error('Error creating anime:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

// PUT /api/anime/:id - Update anime (Admin)
app.put('/api/anime/:id', (req, res) => {
  try {
    const { id } = req.params;
    const existing = db.prepare('SELECT * FROM anime WHERE id = ?').get(id);
    if (!existing) {
      return res.status(404).json({ success: false, error: 'Anime not found' });
    }

    const {
      title,
      japanese_title,
      slug,
      synopsis,
      banner_image,
      poster_image,
      trailer_url,
      video_url,
      rating,
      match_score,
      release_year,
      age_rating,
      season_count,
      quality,
      audio_languages,
      subtitles,
      studio,
      is_featured,
      is_trending,
      is_popular,
      top_10_rank,
      status,
      genres
    } = req.body;

    if (is_featured) {
      db.prepare('UPDATE anime SET is_featured = 0 WHERE id != ?').run(id);
    }

    db.prepare(`
      UPDATE anime SET
        title = COALESCE(@title, title),
        japanese_title = COALESCE(@japanese_title, japanese_title),
        slug = COALESCE(@slug, slug),
        synopsis = COALESCE(@synopsis, synopsis),
        banner_image = COALESCE(@banner_image, banner_image),
        poster_image = COALESCE(@poster_image, poster_image),
        trailer_url = COALESCE(@trailer_url, trailer_url),
        video_url = COALESCE(@video_url, video_url),
        rating = COALESCE(@rating, rating),
        match_score = COALESCE(@match_score, match_score),
        release_year = COALESCE(@release_year, release_year),
        age_rating = COALESCE(@age_rating, age_rating),
        season_count = COALESCE(@season_count, season_count),
        quality = COALESCE(@quality, quality),
        audio_languages = COALESCE(@audio_languages, audio_languages),
        subtitles = COALESCE(@subtitles, subtitles),
        studio = COALESCE(@studio, studio),
        is_featured = COALESCE(@is_featured, is_featured),
        is_trending = COALESCE(@is_trending, is_trending),
        is_popular = COALESCE(@is_popular, is_popular),
        top_10_rank = @top_10_rank,
        status = COALESCE(@status, status),
        updated_at = CURRENT_TIMESTAMP
      WHERE id = @id
    `).run({
      id,
      title: title !== undefined ? title : existing.title,
      japanese_title: japanese_title !== undefined ? japanese_title : existing.japanese_title,
      slug: slug !== undefined ? slug : existing.slug,
      synopsis: synopsis !== undefined ? synopsis : existing.synopsis,
      banner_image: banner_image !== undefined ? banner_image : existing.banner_image,
      poster_image: poster_image !== undefined ? poster_image : existing.poster_image,
      trailer_url: trailer_url !== undefined ? trailer_url : existing.trailer_url,
      video_url: video_url !== undefined ? video_url : existing.video_url,
      rating: rating !== undefined ? parseFloat(rating) : existing.rating,
      match_score: match_score !== undefined ? parseInt(match_score, 10) : existing.match_score,
      release_year: release_year !== undefined ? parseInt(release_year, 10) : existing.release_year,
      age_rating: age_rating !== undefined ? age_rating : existing.age_rating,
      season_count: season_count !== undefined ? season_count : existing.season_count,
      quality: quality !== undefined ? quality : existing.quality,
      audio_languages: audio_languages !== undefined ? audio_languages : existing.audio_languages,
      subtitles: subtitles !== undefined ? subtitles : existing.subtitles,
      studio: studio !== undefined ? studio : existing.studio,
      is_featured: is_featured !== undefined ? (is_featured ? 1 : 0) : existing.is_featured,
      is_trending: is_trending !== undefined ? (is_trending ? 1 : 0) : existing.is_trending,
      is_popular: is_popular !== undefined ? (is_popular ? 1 : 0) : existing.is_popular,
      top_10_rank: top_10_rank !== undefined && top_10_rank !== '' ? parseInt(top_10_rank, 10) : null,
      status: status !== undefined ? status : existing.status
    });

    // Update genres if provided
    if (genres !== undefined) {
      db.prepare('DELETE FROM anime_genres WHERE anime_id = ?').run(id);
      const insertAG = db.prepare('INSERT OR IGNORE INTO anime_genres (anime_id, genre_id) VALUES (?, ?)');
      for (const g of genres) {
        if (typeof g === 'number') {
          insertAG.run(id, g);
        } else if (typeof g === 'string') {
          const gRow = db.prepare('SELECT id FROM genres WHERE name = ? OR slug = ?').get(g, g);
          if (gRow) insertAG.run(id, gRow.id);
        }
      }
    }

    const updated = db.prepare('SELECT * FROM anime WHERE id = ?').get(id);
    res.json({
      success: true,
      message: 'Anime updated successfully',
      data: enrichAnime(updated)
    });
  } catch (error) {
    console.error('Error updating anime:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

// DELETE /api/anime/:id - Delete anime (Admin)
app.delete('/api/anime/:id', (req, res) => {
  try {
    const { id } = req.params;
    const existing = db.prepare('SELECT * FROM anime WHERE id = ?').get(id);
    if (!existing) {
      return res.status(404).json({ success: false, error: 'Anime not found' });
    }

    db.prepare('DELETE FROM anime WHERE id = ?').run(id);
    res.json({ success: true, message: `"${existing.title}" deleted successfully` });
  } catch (error) {
    console.error('Error deleting anime:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

// POST /api/anime/:id/episodes - Add episode
app.post('/api/anime/:id/episodes', (req, res) => {
  try {
    const { id } = req.params;
    const anime = db.prepare('SELECT * FROM anime WHERE id = ?').get(id);
    if (!anime) return res.status(404).json({ success: false, error: 'Anime not found' });

    const { episode_number, title, duration = '24m', thumbnail, video_url, description } = req.body;
    
    // Auto calculate episode number if not provided
    let epNum = episode_number;
    if (!epNum) {
      const maxEp = db.prepare('SELECT MAX(episode_number) as max_ep FROM episodes WHERE anime_id = ?').get(id);
      epNum = (maxEp && maxEp.max_ep) ? maxEp.max_ep + 1 : 1;
    }

    const insertEp = db.prepare(`
      INSERT INTO episodes (anime_id, episode_number, title, duration, thumbnail, video_url, description)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `);

    const result = insertEp.run(
      id,
      epNum,
      title || `Episode ${epNum}`,
      duration,
      thumbnail || anime.banner_image,
      video_url || anime.video_url || 'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4',
      description || `Episode ${epNum} of ${anime.title}`
    );

    const createdEp = db.prepare('SELECT * FROM episodes WHERE id = ?').get(result.lastInsertRowid);
    res.status(201).json({ success: true, data: createdEp });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

// DELETE /api/anime/:id/episodes/:epId - Delete episode
app.delete('/api/anime/:id/episodes/:epId', (req, res) => {
  try {
    const { id, epId } = req.params;
    db.prepare('DELETE FROM episodes WHERE id = ? AND anime_id = ?').run(epId, id);
    res.json({ success: true, message: 'Episode deleted' });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

// POST /api/genres - Create genre
app.post('/api/genres', (req, res) => {
  try {
    const { name } = req.body;
    if (!name) return res.status(400).json({ success: false, error: 'Genre name is required' });

    const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)+/g, '');
    const result = db.prepare('INSERT INTO genres (name, slug) VALUES (?, ?)').run(name, slug);
    const created = db.prepare('SELECT * FROM genres WHERE id = ?').get(result.lastInsertRowid);

    res.status(201).json({ success: true, data: created });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

// DELETE /api/genres/:id - Delete genre
app.delete('/api/genres/:id', (req, res) => {
  try {
    const { id } = req.params;
    db.prepare('DELETE FROM genres WHERE id = ?').run(id);
    res.json({ success: true, message: 'Genre deleted' });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

// POST /api/seed/reset - Reset and reseed database
app.post('/api/seed/reset', (req, res) => {
  try {
    seedDatabase();
    res.json({ success: true, message: 'Catalog reseeded successfully to default high-definition library' });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

// Serve frontend in production build if exists
const clientDistPath = path.join(__dirname, '../client/dist');
app.use(express.static(clientDistPath));

app.get('*', (req, res, next) => {
  if (req.path.startsWith('/api')) {
    return next();
  }
  const indexPath = path.join(clientDistPath, 'index.html');
  res.sendFile(indexPath, (err) => {
    if (err) {
      res.status(404).send('Animeflix API Server running on port 5000. Start client with npm run dev in client directory.');
    }
  });
});

app.listen(PORT, () => {
  console.log(`🚀 Animeflix Server running on http://localhost:${PORT}`);
});
