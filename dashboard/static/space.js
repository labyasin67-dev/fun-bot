(function () {
  const canvas = document.getElementById("space-bg");
  if (!canvas || !canvas.getContext) return;

  const ctx = canvas.getContext("2d", { alpha: false });
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const isMobile = window.matchMedia("(max-width: 800px)").matches;

  let width = 0;
  let height = 0;
  let dpr = 1;
  let stars = [];
  let shooting = null;
  let nextShoot = 0;
  let last = 0;
  let running = false;

  const LAYERS = [
    { count: isMobile ? 40 : 80, size: [0.6, 1.2], speed: 0.012, twinkle: 0.2, color: "rgba(255,255,255,0.45)" },
    { count: isMobile ? 28 : 55, size: [0.9, 1.8], speed: 0.03, twinkle: 0.35, color: "rgba(255,210,210,0.7)" },
    { count: isMobile ? 14 : 28, size: [1.3, 2.4], speed: 0.055, twinkle: 0.5, color: "rgba(255,255,255,0.95)" },
  ];

  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    width = window.innerWidth;
    height = window.innerHeight;
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
    canvas.style.width = width + "px";
    canvas.style.height = height + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    seed();
    if (reduced) draw(0, true);
  }

  function seed() {
    stars = [];
    for (const layer of LAYERS) {
      for (let i = 0; i < layer.count; i++) {
        stars.push({
          x: Math.random() * width,
          y: Math.random() * height,
          r: layer.size[0] + Math.random() * (layer.size[1] - layer.size[0]),
          speed: layer.speed * (0.6 + Math.random() * 0.8),
          twinkle: layer.twinkle,
          phase: Math.random() * Math.PI * 2,
          color: layer.color,
        });
      }
    }
    nextShoot = 4000 + Math.random() * 8000;
  }

  function fillBackground() {
    const g = ctx.createLinearGradient(0, 0, 0, height);
    g.addColorStop(0, "#07060c");
    g.addColorStop(0.55, "#0c0814");
    g.addColorStop(1, "#14080e");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, width, height);
  }

  function drawStar(star, t, frozen) {
    let alphaBoost = 1;
    if (!frozen && star.twinkle) {
      alphaBoost = 0.55 + 0.45 * Math.sin(t * 0.0018 + star.phase);
    }
    ctx.beginPath();
    ctx.fillStyle = star.color;
    ctx.globalAlpha = alphaBoost;
    ctx.arc(star.x, star.y, star.r, 0, Math.PI * 2);
    ctx.fill();
    ctx.globalAlpha = 1;
  }

  function spawnShoot() {
    shooting = {
      x: Math.random() * width * 0.7,
      y: Math.random() * height * 0.4,
      vx: 1.6 + Math.random() * 1.2,
      vy: 0.7 + Math.random() * 0.6,
      life: 0,
      max: 700 + Math.random() * 400,
    };
  }

  function drawShoot(dt) {
    if (!shooting) return;
    shooting.life += dt;
    shooting.x += shooting.vx * dt * 0.35;
    shooting.y += shooting.vy * dt * 0.35;
    const fade = 1 - shooting.life / shooting.max;
    if (fade <= 0) {
      shooting = null;
      nextShoot = 6000 + Math.random() * 10000;
      return;
    }
    ctx.strokeStyle = "rgba(255,220,220," + (0.85 * fade) + ")";
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    ctx.moveTo(shooting.x, shooting.y);
    ctx.lineTo(shooting.x - shooting.vx * 28, shooting.y - shooting.vy * 28);
    ctx.stroke();
  }

  function draw(t, frozen) {
    fillBackground();
    for (const star of stars) {
      if (!frozen) {
        star.y += star.speed * (t && last ? Math.min(t - last, 40) : 16);
        if (star.y > height + 2) {
          star.y = -2;
          star.x = Math.random() * width;
        }
      }
      drawStar(star, t, frozen);
    }
    if (!frozen) drawShoot(t && last ? Math.min(t - last, 40) : 16);
  }

  function frame(t) {
    if (!running) return;
    if (!last) last = t;
    if (!shooting) {
      nextShoot -= t - last;
      if (nextShoot <= 0) spawnShoot();
    }
    draw(t, false);
    last = t;
    requestAnimationFrame(frame);
  }

  function start() {
    if (reduced) {
      draw(0, true);
      return;
    }
    if (running) return;
    running = true;
    last = 0;
    requestAnimationFrame(frame);
  }

  function stop() {
    running = false;
  }

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) stop();
    else start();
  });

  window.addEventListener("resize", resize);
  resize();
  start();
})();
