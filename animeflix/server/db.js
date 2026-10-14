const Database = require('better-sqlite3');
const path = require('path');

const dbPath = path.join(__dirname, 'animeflix.db');
const db = new Database(dbPath);

// Enable foreign keys and WAL mode for performance
db.pragma('journal_mode = WAL');
db.pragma('foreign_keys = ON');

function initDatabase() {
  // Create tables
  db.exec(`
    CREATE TABLE IF NOT EXISTS genres (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT UNIQUE NOT NULL,
      slug TEXT UNIQUE NOT NULL
    );

    CREATE TABLE IF NOT EXISTS anime (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      title TEXT NOT NULL,
      japanese_title TEXT,
      slug TEXT UNIQUE NOT NULL,
      synopsis TEXT,
      banner_image TEXT NOT NULL,
      poster_image TEXT NOT NULL,
      trailer_url TEXT,
      video_url TEXT,
      rating REAL DEFAULT 8.5,
      match_score INTEGER DEFAULT 95,
      release_year INTEGER DEFAULT 2024,
      age_rating TEXT DEFAULT 'TV-MA',
      season_count TEXT DEFAULT '1 Season',
      quality TEXT DEFAULT '4K Ultra HD',
      audio_languages TEXT DEFAULT 'Japanese [Original], English',
      subtitles TEXT DEFAULT 'English, Spanish, French, German',
      studio TEXT DEFAULT 'MAPPA',
      is_featured INTEGER DEFAULT 0,
      is_trending INTEGER DEFAULT 0,
      is_popular INTEGER DEFAULT 0,
      top_10_rank INTEGER DEFAULT NULL,
      status TEXT DEFAULT 'Ongoing',
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS anime_genres (
      anime_id INTEGER NOT NULL,
      genre_id INTEGER NOT NULL,
      PRIMARY KEY (anime_id, genre_id),
      FOREIGN KEY (anime_id) REFERENCES anime(id) ON DELETE CASCADE,
      FOREIGN KEY (genre_id) REFERENCES genres(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS episodes (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      anime_id INTEGER NOT NULL,
      episode_number INTEGER NOT NULL,
      title TEXT NOT NULL,
      duration TEXT DEFAULT '24m',
      thumbnail TEXT,
      video_url TEXT,
      description TEXT,
      FOREIGN KEY (anime_id) REFERENCES anime(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS my_list (
      user_id TEXT NOT NULL DEFAULT 'default_user',
      anime_id INTEGER NOT NULL,
      added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY (user_id, anime_id),
      FOREIGN KEY (anime_id) REFERENCES anime(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS likes (
      user_id TEXT NOT NULL DEFAULT 'default_user',
      anime_id INTEGER NOT NULL,
      liked INTEGER NOT NULL, -- 1 for like, -1 for dislike
      PRIMARY KEY (user_id, anime_id),
      FOREIGN KEY (anime_id) REFERENCES anime(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS watch_history (
      user_id TEXT NOT NULL DEFAULT 'default_user',
      anime_id INTEGER NOT NULL,
      episode_id INTEGER,
      progress_percent INTEGER DEFAULT 15,
      last_watched DATETIME DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY (user_id, anime_id),
      FOREIGN KEY (anime_id) REFERENCES anime(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS admin_config (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );
  `);

  // Set default admin PIN / password if not present
  const adminCheck = db.prepare(`SELECT value FROM admin_config WHERE key = 'admin_password'`).get();
  if (!adminCheck) {
    db.prepare(`INSERT INTO admin_config (key, value) VALUES ('admin_password', 'animeflix2025')`).run();
  }

  // Check if anime table is empty; if so, seed default data
  const count = db.prepare('SELECT COUNT(*) as count FROM anime').get().count;
  if (count === 0) {
    seedDatabase();
  }
}

function seedDatabase() {
  console.log('🌱 Seeding initial Animeflix catalog...');

  // Clear existing
  db.exec(`
    DELETE FROM anime_genres;
    DELETE FROM episodes;
    DELETE FROM my_list;
    DELETE FROM watch_history;
    DELETE FROM likes;
    DELETE FROM anime;
    DELETE FROM genres;
  `);

  const genresList = [
    { name: 'Action', slug: 'action' },
    { name: 'Shonen', slug: 'shonen' },
    { name: 'Dark Fantasy', slug: 'dark-fantasy' },
    { name: 'Supernatural', slug: 'supernatural' },
    { name: 'Sci-Fi', slug: 'sci-fi' },
    { name: 'Cyberpunk', slug: 'cyberpunk' },
    { name: 'Slice of Life', slug: 'slice-of-life' },
    { name: 'Comedy', slug: 'comedy' },
    { name: 'Psychological', slug: 'psychological' },
    { name: 'Adventure', slug: 'adventure' },
    { name: 'Mystery', slug: 'mystery' },
    { name: 'Romance', slug: 'romance' },
    { name: 'Drama', slug: 'drama' }
  ];

  const insertGenre = db.prepare('INSERT INTO genres (name, slug) VALUES (?, ?)');
  const genreMap = {};
  for (const g of genresList) {
    const res = insertGenre.run(g.name, g.slug);
    genreMap[g.name] = res.lastInsertRowid;
  }

  // High quality sample MP4 video streams and anime videos
  const sampleVideos = [
    'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4',
    'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ElephantsDream.mp4',
    'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4',
    'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerEscapes.mp4',
    'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/TearsOfSteel.mp4',
    'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/Sintel.mp4'
  ];

  const animeList = [
    {
      title: 'Solo Leveling',
      japanese_title: '俺だけレベルアップな件 (Ore dake Level Up na Ken)',
      slug: 'solo-leveling',
      synopsis: 'In a world where hunters, humans who possess magical abilities, battle deadly monsters to protect humanity, Sung Jinwoo, notoriously known as the "Weakest Hunter of All Humanity", awakens a mysterious quest system after surviving a deadly double dungeon.',
      banner_image: 'https://images.unsplash.com/photo-1578632767115-351597cf2477?auto=format&fit=crop&w=1920&q=80',
      poster_image: 'https://images.unsplash.com/photo-1563089145-599997674d42?auto=format&fit=crop&w=600&q=80',
      trailer_url: 'https://www.youtube.com/watch?v=k8v5XwMoxW0',
      video_url: sampleVideos[0],
      rating: 9.4,
      match_score: 99,
      release_year: 2024,
      age_rating: 'TV-MA',
      season_count: '2 Seasons',
      quality: '4K Ultra HD',
      audio_languages: 'Japanese [Original], English, Hindi, Portuguese',
      subtitles: 'English, Spanish, French, German, Japanese, Korean',
      studio: 'A-1 Pictures',
      is_featured: 1,
      is_trending: 1,
      is_popular: 1,
      top_10_rank: 1,
      status: 'Ongoing',
      genres: ['Action', 'Dark Fantasy', 'Supernatural', 'Adventure'],
      episodes: [
        { episode_number: 1, title: 'I\'m Used to It', duration: '24m', description: 'Jinwoo joins a low-rank raid squad into a D-Rank dungeon, but a hidden path leads to an apocalyptic slaughter.' },
        { episode_number: 2, title: 'If I Had One More Chance', duration: '24m', description: 'Facing the statues of the Cartenon Temple, Jinwoo solves the commandments as his comrades fall one by one.' },
        { episode_number: 3, title: 'It\'s Like a Game', duration: '23m', description: 'Jinwoo awakens in a hospital bed with an interactive interface only he can see.' },
        { episode_number: 4, title: 'I\'ve Gotta Get Stronger', duration: '24m', description: 'Jinwoo enters an instant dungeon inside a subway station and battles mutated steel-fang lycans.' },
        { episode_number: 5, title: 'A Pretty Good Deal', duration: '25m', description: 'Jinwoo is hired to fill out an assault team led by Hwang Dongsuk into a C-Rank dungeon.' }
      ]
    },
    {
      title: 'Jujutsu Kaisen',
      japanese_title: '呪術廻戦 (Jujutsu Kaisen)',
      slug: 'jujutsu-kaisen',
      synopsis: 'Yuji Itadori, a kind-hearted teenager with superhuman physical strength, swallows a cursed talisman—the decaying finger of the legendary Curse Ryomen Sukuna—to protect his friends, thrusting him into the perilous world of Jujutsu Sorcerers.',
      banner_image: 'https://images.unsplash.com/photo-1607604276583-eef5d076aa5f?auto=format&fit=crop&w=1920&q=80',
      poster_image: 'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&w=600&q=80',
      trailer_url: 'https://www.youtube.com/watch?v=pkKu8Uhi2-g',
      video_url: sampleVideos[1],
      rating: 9.3,
      match_score: 98,
      release_year: 2023,
      age_rating: 'TV-MA',
      season_count: '2 Seasons',
      quality: '4K Ultra HD',
      audio_languages: 'Japanese [Original], English, Spanish, French',
      subtitles: 'English, Spanish, French, German, Italian',
      studio: 'MAPPA',
      is_featured: 0,
      is_trending: 1,
      is_popular: 1,
      top_10_rank: 2,
      status: 'Ongoing',
      genres: ['Action', 'Supernatural', 'Dark Fantasy', 'Shonen'],
      episodes: [
        { episode_number: 1, title: 'Ryomen Sukuna', duration: '24m', description: 'Yuji Itadori makes a fateful choice to swallow a special-grade cursed object.' },
        { episode_number: 2, title: 'For Myself', duration: '24m', description: 'Satoru Gojo brings Yuji to Jujutsu High to meet Principal Yaga.' },
        { episode_number: 3, title: 'Girl of Steel', duration: '24m', description: 'Yuji and Megumi meet Nobara Kugisaki and are tasked with exorcising an abandoned building in Roppongi.' },
        { episode_number: 4, title: 'Curse Womb Must Die', duration: '24m', description: 'The first-years face an unexpected Special Grade curse at a juvenile detention facility.' }
      ]
    },
    {
      title: 'Attack on Titan',
      japanese_title: '進撃の巨人 (Shingeki no Kyojin)',
      slug: 'attack-on-titan',
      synopsis: 'After his hometown is destroyed and his mother is killed by giant humanoid Titans, Eren Yeager vows to cleanse the earth of the giant Titans that have brought humanity to the brink of extinction.',
      banner_image: 'https://images.unsplash.com/photo-1534447677768-be436bb09401?auto=format&fit=crop&w=1920&q=80',
      poster_image: 'https://images.unsplash.com/photo-1518709268805-4e9042af9f23?auto=format&fit=crop&w=600&q=80',
      trailer_url: 'https://www.youtube.com/watch?v=MGRm4IzK1SQ',
      video_url: sampleVideos[2],
      rating: 9.6,
      match_score: 99,
      release_year: 2023,
      age_rating: 'TV-MA',
      season_count: '4 Seasons',
      quality: '4K Ultra HD',
      audio_languages: 'Japanese [Original], English, German, French',
      subtitles: 'English, Spanish, French, German, Arabic',
      studio: 'MAPPA / Wit Studio',
      is_featured: 0,
      is_trending: 1,
      is_popular: 1,
      top_10_rank: 3,
      status: 'Completed',
      genres: ['Action', 'Dark Fantasy', 'Mystery', 'Drama', 'Psychological'],
      episodes: [
        { episode_number: 1, title: 'To You, in 2000 Years: The Fall of Shiganshina, Part 1', duration: '24m', description: 'A massive Colossal Titan smashes through the outer wall of humanity\'s refuge.' },
        { episode_number: 2, title: 'That Day: The Fall of Shiganshina, Part 2', duration: '24m', description: 'Eren, Mikasa, and Armin escape aboard an evacuation ship as Wall Maria falls.' },
        { episode_number: 3, title: 'A Dim Light Amid Despair: Humanity\'s Comeback, Part 1', duration: '24m', description: 'Eren begins his training in the 104th Cadet Corps.' }
      ]
    },
    {
      title: 'Demon Slayer: Kimetsu no Yaiba',
      japanese_title: '鬼滅の刃 (Kimetsu no Yaiba)',
      slug: 'demon-slayer',
      synopsis: 'Tanjiro Kamado, a young coal merchant whose family is slaughtered by demons and whose younger sister Nezuko is turned into a demon, embarks on a quest to become a demon slayer and find a cure to turn Nezuko human again.',
      banner_image: 'https://images.unsplash.com/photo-1579783900882-c0d3dad7b119?auto=format&fit=crop&w=1920&q=80',
      poster_image: 'https://images.unsplash.com/photo-1563089145-599997674d42?auto=format&fit=crop&w=600&q=80',
      trailer_url: 'https://www.youtube.com/watch?v=VQGCKyvzIM4',
      video_url: sampleVideos[3],
      rating: 9.2,
      match_score: 97,
      release_year: 2024,
      age_rating: 'TV-14',
      season_count: '4 Seasons',
      quality: '4K Ultra HD',
      audio_languages: 'Japanese [Original], English, Spanish, Japanese Audio Description',
      subtitles: 'English, Spanish, French, German, Simplified Chinese',
      studio: 'Ufotable',
      is_featured: 0,
      is_trending: 1,
      is_popular: 1,
      top_10_rank: 4,
      status: 'Ongoing',
      genres: ['Action', 'Dark Fantasy', 'Supernatural', 'Shonen'],
      episodes: [
        { episode_number: 1, title: 'Cruelty', duration: '24m', description: 'Tanjiro returns home from town to discover a tragedy that changes his destiny forever.' },
        { episode_number: 2, title: 'Trainer Sakonji Urokodaki', duration: '24m', description: 'Giyu Tomioka directs Tanjiro to Mount Sagiri to seek training.' },
        { episode_number: 3, title: 'Sabito and Makomo', duration: '24m', description: 'Tanjiro struggles with the final boulder test until two masked spirits appear.' }
      ]
    },
    {
      title: 'Frieren: Beyond Journey\'s End',
      japanese_title: '葬送のフリーレン (Sousou no Frieren)',
      slug: 'frieren-beyond-journeys-end',
      synopsis: 'The elf mage Frieren and her courageous fellow adventurers have defeated the Demon King and brought peace to the land. But as an elf with a lifespan of over a thousand years, she must watch her human companions pass away, prompting a new journey to understand humanity.',
      banner_image: 'https://images.unsplash.com/photo-1518709268805-4e9042af9f23?auto=format&fit=crop&w=1920&q=80',
      poster_image: 'https://images.unsplash.com/photo-1534447677768-be436bb09401?auto=format&fit=crop&w=600&q=80',
      trailer_url: 'https://www.youtube.com/watch?v=Qke6O4kX72E',
      video_url: sampleVideos[4],
      rating: 9.7,
      match_score: 99,
      release_year: 2024,
      age_rating: 'TV-14',
      season_count: '1 Season',
      quality: '4K Ultra HD',
      audio_languages: 'Japanese [Original], English, German',
      subtitles: 'English, Spanish, French, German, Italian, Portuguese',
      studio: 'Madhouse',
      is_featured: 0,
      is_trending: 1,
      is_popular: 1,
      top_10_rank: 5,
      status: 'Completed',
      genres: ['Adventure', 'Drama', 'Slice of Life', 'Dark Fantasy'],
      episodes: [
        { episode_number: 1, title: 'The Journey\'s End', duration: '25m', description: 'The hero party returns to the capital after a ten-year quest to defeat the Demon King.' },
        { episode_number: 2, title: 'It Didn\'t Have to Be Magic...', duration: '24m', description: 'Frieren takes on Fern as an apprentice mage under the dying wish of Heiter.' },
        { episode_number: 3, title: 'Killing Magic', duration: '24m', description: 'Frieren and Fern visit a village where a sealed demon named Qual is about to awaken.' }
      ]
    },
    {
      title: 'Chainsaw Man',
      japanese_title: 'チェンソーマン (Chainsaw Man)',
      slug: 'chainsaw-man',
      synopsis: 'Denji is a teenage boy living with a Chainsaw Devil named Pochita. Due to the debt his father left behind, he is living a bottom-of-the-barrel life while repaying his debt by harvesting devil corpses with Pochita, until a betrayal fuses him with Pochita\'s heart.',
      banner_image: 'https://images.unsplash.com/photo-1578632767115-351597cf2477?auto=format&fit=crop&w=1920&q=80',
      poster_image: 'https://images.unsplash.com/photo-1607604276583-eef5d076aa5f?auto=format&fit=crop&w=600&q=80',
      trailer_url: 'https://www.youtube.com/watch?v=jk7QXRWwyw8',
      video_url: sampleVideos[5],
      rating: 8.9,
      match_score: 94,
      release_year: 2022,
      age_rating: 'TV-MA',
      season_count: '1 Season',
      quality: '4K Ultra HD',
      audio_languages: 'Japanese [Original], English, French',
      subtitles: 'English, Spanish, French, German, Japanese',
      studio: 'MAPPA',
      is_featured: 0,
      is_trending: 1,
      is_popular: 1,
      top_10_rank: 6,
      status: 'Ongoing',
      genres: ['Action', 'Dark Fantasy', 'Supernatural', 'Comedy'],
      episodes: [
        { episode_number: 1, title: 'Dog & Chainsaw', duration: '24m', description: 'Denji lives as a destitute devil hunter alongside his chainsaw devil dog Pochita.' },
        { episode_number: 2, title: 'Arrival in Tokyo', duration: '24m', description: 'Makima brings Denji to Public Safety Devil Hunter Headquarters in Tokyo.' },
        { episode_number: 3, title: 'Meowy\'s Whereabouts', duration: '24m', description: 'Denji is paired up with Power, the blood fiend, on a rescue mission for her pet cat.' }
      ]
    },
    {
      title: 'Cyberpunk: Edgerunners',
      japanese_title: 'サイバーパンク エッジランナーズ',
      slug: 'cyberpunk-edgerunners',
      synopsis: 'A street kid trying to survive in a technology and body modification-obsessed city of the future. Having everything to lose, he chooses to stay alive by becoming an edgerunner: a mercenary outlaw also known as a cyberpunk.',
      banner_image: 'https://images.unsplash.com/photo-1509198397868-475647b2a1e5?auto=format&fit=crop&w=1920&q=80',
      poster_image: 'https://images.unsplash.com/photo-1542751371-adc38448a05e?auto=format&fit=crop&w=600&q=80',
      trailer_url: 'https://www.youtube.com/watch?v=JtqIas3bYhg',
      video_url: sampleVideos[0],
      rating: 9.1,
      match_score: 96,
      release_year: 2022,
      age_rating: 'TV-MA',
      season_count: '1 Season',
      quality: '4K Ultra HD',
      audio_languages: 'English [Original], Japanese, German, Polish, Spanish',
      subtitles: 'English, Spanish, French, German, Polish, Japanese',
      studio: 'Studio Trigger / CD Projekt',
      is_featured: 0,
      is_trending: 1,
      is_popular: 1,
      top_10_rank: 7,
      status: 'Completed',
      genres: ['Cyberpunk', 'Sci-Fi', 'Action', 'Drama'],
      episodes: [
        { episode_number: 1, title: 'Let You Down', duration: '24m', description: 'David Martinez struggles to fit in at the prestigious Arasaka Academy while living in Santo Domingo.' },
        { episode_number: 2, title: 'Like a Boy', duration: '25m', description: 'With a military-grade Sandevistan cyberware installed in his spine, David meets a mysterious netrunner named Lucy.' },
        { episode_number: 3, title: 'Smooth Criminal', duration: '24m', description: 'David is introduced to Maine and his crew of hardened edgerunners.' }
      ]
    },
    {
      title: 'One Piece',
      japanese_title: 'ワンピース (ONE PIECE)',
      slug: 'one-piece',
      synopsis: 'Monkey D. Luffy, a boy whose body gained the properties of rubber after unintentionally eating a Devil Fruit, sets out on the Grand Line with his pirate crew, named the Straw Hat Pirates, to find the legendary treasure known as "One Piece" and become King of the Pirates.',
      banner_image: 'https://images.unsplash.com/photo-1563089145-599997674d42?auto=format&fit=crop&w=1920&q=80',
      poster_image: 'https://images.unsplash.com/photo-1578632767115-351597cf2477?auto=format&fit=crop&w=600&q=80',
      trailer_url: 'https://www.youtube.com/watch?v=l_98K4_6UQ0',
      video_url: sampleVideos[1],
      rating: 9.5,
      match_score: 99,
      release_year: 2024,
      age_rating: 'TV-14',
      season_count: '21 Seasons',
      quality: 'HD',
      audio_languages: 'Japanese [Original], English, Spanish',
      subtitles: 'English, Spanish, French, German, Arabic',
      studio: 'Toei Animation',
      is_featured: 0,
      is_trending: 1,
      is_popular: 1,
      top_10_rank: 8,
      status: 'Ongoing',
      genres: ['Action', 'Adventure', 'Comedy', 'Shonen'],
      episodes: [
        { episode_number: 1089, title: 'Entering a New Chapter! Luffy and Bonney\'s Paths!', duration: '24m', description: 'The Straw Hats arrive at the futuristic island of Egghead, home to Dr. Vegapunk.' },
        { episode_number: 1090, title: 'A New Island! Future Island Egghead', duration: '24m', description: 'Luffy, Chopper, and Jinbe encounter robotic wonders and ancient secrets.' }
      ]
    },
    {
      title: 'Bleach: Thousand-Year Blood War',
      japanese_title: 'BLEACH 千年血戦篇',
      slug: 'bleach-tybw',
      synopsis: 'The peace is suddenly broken when warning sirens blare through the Soul Society. Residents there are disappearing without a trace and nobody knows who is behind it. Meanwhile, a dark shadow is also extending towards Ichigo and his friends in Karakura Town.',
      banner_image: 'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&w=1920&q=80',
      poster_image: 'https://images.unsplash.com/photo-1534447677768-be436bb09401?auto=format&fit=crop&w=600&q=80',
      trailer_url: 'https://www.youtube.com/watch?v=e8YBesRKq_U',
      video_url: sampleVideos[2],
      rating: 9.3,
      match_score: 97,
      release_year: 2024,
      age_rating: 'TV-MA',
      season_count: '3 Parts',
      quality: '4K Ultra HD',
      audio_languages: 'Japanese [Original], English',
      subtitles: 'English, Spanish, French, German',
      studio: 'Pierrot',
      is_featured: 0,
      is_trending: 1,
      is_popular: 1,
      top_10_rank: 9,
      status: 'Ongoing',
      genres: ['Action', 'Supernatural', 'Shonen'],
      episodes: [
        { episode_number: 1, title: 'The Blood Warfare', duration: '24m', description: 'The Wandenreich, an empire of Quincies led by Yhwach, declares war on the Soul Society.' },
        { episode_number: 2, title: 'Foundation Stones', duration: '24m', description: 'Ichigo travels to Hueco Mundo to rescue the Arrancars from the Quincy army.' }
      ]
    },
    {
      title: 'Spy x Family',
      japanese_title: 'SPY×FAMILY (スパイファミリー)',
      slug: 'spy-x-family',
      synopsis: 'Master spy Twilight is tasked with Operation Strix, which requires him to build a faux family in order to infiltrate a prestigious school. Little does he know that his adopted daughter is a telepath and his fake wife is a lethal assassin.',
      banner_image: 'https://images.unsplash.com/photo-1579783900882-c0d3dad7b119?auto=format&fit=crop&w=1920&q=80',
      poster_image: 'https://images.unsplash.com/photo-1509198397868-475647b2a1e5?auto=format&fit=crop&w=600&q=80',
      trailer_url: 'https://www.youtube.com/watch?v=ofXigq9aIpo',
      video_url: sampleVideos[3],
      rating: 8.8,
      match_score: 95,
      release_year: 2023,
      age_rating: 'TV-14',
      season_count: '2 Seasons',
      quality: '4K Ultra HD',
      audio_languages: 'Japanese [Original], English, Spanish, German',
      subtitles: 'English, Spanish, French, German, Italian',
      studio: 'Wit Studio / CloverWorks',
      is_featured: 0,
      is_trending: 0,
      is_popular: 1,
      top_10_rank: 10,
      status: 'Ongoing',
      genres: ['Comedy', 'Slice of Life', 'Action', 'Mystery'],
      episodes: [
        { episode_number: 1, title: 'Operation Strix', duration: '24m', description: 'Twilight adopts a mischievous orphan named Anya to fulfill his mission.' },
        { episode_number: 2, title: 'Secure a Wife', duration: '24m', description: 'Loid meets Yor Briar at a tailor shop and proposes a mutually beneficial arrangement.' }
      ]
    },
    {
      title: 'Death Note',
      japanese_title: 'DEATH NOTE (デスノート)',
      slug: 'death-note',
      synopsis: 'Light Yagami, a brilliant high school student, stumbles upon a supernatural notebook dropped by the Shinigami Ryuk. The notebook grants the user the ability to kill anyone whose name and face are known to the writer.',
      banner_image: 'https://images.unsplash.com/photo-1607604276583-eef5d076aa5f?auto=format&fit=crop&w=1920&q=80',
      poster_image: 'https://images.unsplash.com/photo-1518709268805-4e9042af9f23?auto=format&fit=crop&w=600&q=80',
      trailer_url: 'https://www.youtube.com/watch?v=NlJZ-YgAt-c',
      video_url: sampleVideos[4],
      rating: 9.0,
      match_score: 96,
      release_year: 2007,
      age_rating: 'TV-14',
      season_count: '1 Season',
      quality: 'HD',
      audio_languages: 'Japanese [Original], English, French, Portuguese',
      subtitles: 'English, Spanish, French, German',
      studio: 'Madhouse',
      is_featured: 0,
      is_trending: 0,
      is_popular: 1,
      top_10_rank: null,
      status: 'Completed',
      genres: ['Psychological', 'Mystery', 'Supernatural', 'Drama'],
      episodes: [
        { episode_number: 1, title: 'Rebirth', duration: '23m', description: 'Light Yagami finds the Death Note and begins his crusade to rid the world of evil.' },
        { episode_number: 2, title: 'Confrontation', duration: '23m', description: 'The enigmatic detective L broadcasts a global trap to narrow down Kira\'s location.' }
      ]
    },
    {
      title: 'Fullmetal Alchemist: Brotherhood',
      japanese_title: '鋼の錬金術師 FULLMETAL ALCHEMIST',
      slug: 'fullmetal-alchemist-brotherhood',
      synopsis: 'Two alchemist brothers, Edward and Alphonse Elric, search for the Philosopher\'s Stone to restore their bodies after a catastrophic failed attempt to bring their mother back to life using human transmutation.',
      banner_image: 'https://images.unsplash.com/photo-1534447677768-be436bb09401?auto=format&fit=crop&w=1920&q=80',
      poster_image: 'https://images.unsplash.com/photo-1578632767115-351597cf2477?auto=format&fit=crop&w=600&q=80',
      trailer_url: 'https://www.youtube.com/watch?v=--IcmZkvL0Q',
      video_url: sampleVideos[5],
      rating: 9.8,
      match_score: 100,
      release_year: 2010,
      age_rating: 'TV-14',
      season_count: '5 Parts',
      quality: 'HD',
      audio_languages: 'Japanese [Original], English',
      subtitles: 'English, Spanish, French',
      studio: 'Bones',
      is_featured: 0,
      is_trending: 0,
      is_popular: 1,
      top_10_rank: null,
      status: 'Completed',
      genres: ['Action', 'Adventure', 'Dark Fantasy', 'Shonen'],
      episodes: [
        { episode_number: 1, title: 'Fullmetal Alchemist', duration: '24m', description: 'Edward and Alphonse arrive in Central City to confront Isaac McDougal, the Freezing Alchemist.' },
        { episode_number: 2, title: 'The First Day', duration: '24m', description: 'Flashbacks reveal the brothers\' childhood, their mother\'s death, and the forbidden transmutation.' }
      ]
    },
    {
      title: 'Steins;Gate',
      japanese_title: 'シュタインズ・ゲート (Steins;Gate)',
      slug: 'steins-gate',
      synopsis: 'Self-proclaimed mad scientist Rintaro Okabe and his lab members accidentally invent a microwave device capable of sending text messages to the past, triggering unforeseen divergences across worldlines and the timeline itself.',
      banner_image: 'https://images.unsplash.com/photo-1509198397868-475647b2a1e5?auto=format&fit=crop&w=1920&q=80',
      poster_image: 'https://images.unsplash.com/photo-1542751371-adc38448a05e?auto=format&fit=crop&w=600&q=80',
      trailer_url: 'https://www.youtube.com/watch?v=27OZcZohfiY',
      video_url: sampleVideos[0],
      rating: 9.5,
      match_score: 97,
      release_year: 2011,
      age_rating: 'TV-14',
      season_count: '1 Season',
      quality: 'HD',
      audio_languages: 'Japanese [Original], English',
      subtitles: 'English, Spanish, French',
      studio: 'White Fox',
      is_featured: 0,
      is_trending: 0,
      is_popular: 1,
      top_10_rank: null,
      status: 'Completed',
      genres: ['Sci-Fi', 'Psychological', 'Mystery', 'Drama'],
      episodes: [
        { episode_number: 1, title: 'Turning Point', duration: '24m', description: 'Okabe attends a time travel conference and discovers Kurisu Makise lying in a pool of blood.' },
        { episode_number: 2, title: 'Time Travel Paranoia', duration: '24m', description: 'Okabe is shocked to find Kurisu alive and well at a university seminar.' }
      ]
    },
    {
      title: 'Vinland Saga',
      japanese_title: 'ヴィンランド・サガ (Vinland Saga)',
      slug: 'vinland-saga',
      synopsis: 'Thorfinn, son of one of the Vikings\' greatest warriors, is raised by the band of mercenaries who murdered his father, fueled by burning vengeance to challenge their leader Askeladd to a fair duel.',
      banner_image: 'https://images.unsplash.com/photo-1579783900882-c0d3dad7b119?auto=format&fit=crop&w=1920&q=80',
      poster_image: 'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&w=600&q=80',
      trailer_url: 'https://www.youtube.com/watch?v=7U7BDn-gU18',
      video_url: sampleVideos[1],
      rating: 9.4,
      match_score: 98,
      release_year: 2023,
      age_rating: 'TV-MA',
      season_count: '2 Seasons',
      quality: '4K Ultra HD',
      audio_languages: 'Japanese [Original], English, German',
      subtitles: 'English, Spanish, French, German',
      studio: 'MAPPA / Wit Studio',
      is_featured: 0,
      is_trending: 0,
      is_popular: 1,
      top_10_rank: null,
      status: 'Ongoing',
      genres: ['Action', 'Adventure', 'Drama', 'Historical'],
      episodes: [
        { episode_number: 1, title: 'Somewhere Not Here', duration: '24m', description: 'Thorfinn grows up in an Icelandic fishing village listening to tales of the mythical Vinland.' },
        { episode_number: 2, title: 'Sword', duration: '24m', description: 'The legendary warrior Thors is summoned back to war by Floki of the Jomsvikings.' }
      ]
    },
    {
      title: 'Mob Psycho 100',
      japanese_title: 'モブサイコ100 (Mob Psycho 100)',
      slug: 'mob-psycho-100',
      synopsis: 'Shigeo Kageyama, nicknamed "Mob", is an eighth-grader with incredible psychic power who tries to live a normal life and keep his growing emotional percentage below 100%.',
      banner_image: 'https://images.unsplash.com/photo-1578632767115-351597cf2477?auto=format&fit=crop&w=1920&q=80',
      poster_image: 'https://images.unsplash.com/photo-1563089145-599997674d42?auto=format&fit=crop&w=600&q=80',
      trailer_url: 'https://www.youtube.com/watch?v=0n4U3kS_wU0',
      video_url: sampleVideos[2],
      rating: 9.1,
      match_score: 94,
      release_year: 2022,
      age_rating: 'TV-14',
      season_count: '3 Seasons',
      quality: '4K Ultra HD',
      audio_languages: 'Japanese [Original], English',
      subtitles: 'English, Spanish, French',
      studio: 'Bones',
      is_featured: 0,
      is_trending: 0,
      is_popular: 1,
      top_10_rank: null,
      status: 'Completed',
      genres: ['Action', 'Comedy', 'Supernatural', 'Slice of Life'],
      episodes: [
        { episode_number: 1, title: 'Self-Proclaimed Psychic: Reigen Arataka', duration: '24m', description: 'Mob assists his master Reigen in exorcising spirits at an abandoned tunnel.' },
        { episode_number: 2, title: 'Doubts About Youth', duration: '24m', description: 'Mob decides to join the Body Improvement Club instead of the Telepathy Club.' }
      ]
    },
    {
      title: 'Hunter x Hunter',
      japanese_title: 'ハンター×ハンター (HUNTER×HUNTER)',
      slug: 'hunter-x-hunter',
      synopsis: 'Gon Freecss aspires to become a world-class Hunter, an exceptional individual capable of greatness, to track down the father who abandoned him as an infant.',
      banner_image: 'https://images.unsplash.com/photo-1607604276583-eef5d076aa5f?auto=format&fit=crop&w=1920&q=80',
      poster_image: 'https://images.unsplash.com/photo-1518709268805-4e9042af9f23?auto=format&fit=crop&w=600&q=80',
      trailer_url: 'https://www.youtube.com/watch?v=d6kBeJjTGnY',
      video_url: sampleVideos[3],
      rating: 9.6,
      match_score: 99,
      release_year: 2014,
      age_rating: 'TV-14',
      season_count: '6 Seasons',
      quality: 'HD',
      audio_languages: 'Japanese [Original], English, French',
      subtitles: 'English, Spanish, French',
      studio: 'Madhouse',
      is_featured: 0,
      is_trending: 0,
      is_popular: 1,
      top_10_rank: null,
      status: 'Completed',
      genres: ['Action', 'Adventure', 'Dark Fantasy', 'Shonen'],
      episodes: [
        { episode_number: 1, title: 'Departure x And x Friends', duration: '23m', description: 'Gon sets sail from Whale Island to take the grueling Hunter Examination.' },
        { episode_number: 2, title: 'Test x of x Tests', duration: '23m', description: 'Gon, Kurapika, and Leorio face their first riddles from the Navigators.' }
      ]
    }
  ];

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

  const insertAnimeGenre = db.prepare(`
    INSERT OR IGNORE INTO anime_genres (anime_id, genre_id) VALUES (?, ?)
  `);

  const insertEpisode = db.prepare(`
    INSERT INTO episodes (anime_id, episode_number, title, duration, thumbnail, video_url, description)
    VALUES (?, ?, ?, ?, ?, ?, ?)
  `);

  const insertMyList = db.prepare(`
    INSERT OR IGNORE INTO my_list (user_id, anime_id) VALUES ('default_user', ?)
  `);

  const insertWatchHistory = db.prepare(`
    INSERT OR IGNORE INTO watch_history (user_id, anime_id, episode_id, progress_percent) VALUES ('default_user', ?, ?, ?)
  `);

  const seedTransaction = db.transaction(() => {
    animeList.forEach((item, index) => {
      const animeResult = insertAnime.run({
        title: item.title,
        japanese_title: item.japanese_title || '',
        slug: item.slug,
        synopsis: item.synopsis,
        banner_image: item.banner_image,
        poster_image: item.poster_image,
        trailer_url: item.trailer_url,
        video_url: item.video_url,
        rating: item.rating,
        match_score: item.match_score,
        release_year: item.release_year,
        age_rating: item.age_rating,
        season_count: item.season_count,
        quality: item.quality,
        audio_languages: item.audio_languages,
        subtitles: item.subtitles,
        studio: item.studio,
        is_featured: item.is_featured,
        is_trending: item.is_trending,
        is_popular: item.is_popular,
        top_10_rank: item.top_10_rank,
        status: item.status
      });

      const animeId = animeResult.lastInsertRowid;

      // Link genres
      if (item.genres && item.genres.length > 0) {
        for (const gName of item.genres) {
          if (genreMap[gName]) {
            insertAnimeGenre.run(animeId, genreMap[gName]);
          }
        }
      }

      // Add episodes
      if (item.episodes && item.episodes.length > 0) {
        item.episodes.forEach((ep) => {
          insertEpisode.run(
            animeId,
            ep.episode_number,
            ep.title,
            ep.duration,
            ep.thumbnail || item.banner_image,
            item.video_url,
            ep.description
          );
        });
      }

      // Add couple of items to initial My List and Watch History for realism
      if (index === 0 || index === 2 || index === 4) {
        insertMyList.run(animeId);
      }
      if (index === 0) {
        insertWatchHistory.run(animeId, 1, 65);
      }
      if (index === 1) {
        insertWatchHistory.run(animeId, 1, 35);
      }
    });
  });

  seedTransaction();
  console.log(`✅ Seeded ${animeList.length} anime successfully.`);
}

module.exports = {
  db,
  initDatabase,
  seedDatabase
};
