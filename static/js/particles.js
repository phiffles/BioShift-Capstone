class ParticlesBackground {
  constructor(canvasElement, options = {}) {
    this.canvas = canvasElement;
    this.context = this.canvas.getContext('2d');
    this.circles = [];
    this.mouse = { x: 0, y: 0 };
    this.canvasSize = { w: 0, h: 0 };
    this.dpr = window.devicePixelRatio || 1;
    
    this.quantity = options.quantity || 150;
    this.staticity = options.staticity || 50;
    this.ease = options.ease || 50;
    this.size = options.size || 0.4;
    this.color = options.color || '#ffffff';
    this.vx = options.vx || 0;
    this.vy = options.vy || 0;
    
    this.rgb = this.hexToRgb(this.color);

    this.init();
    this.animate = this.animate.bind(this);

    window.addEventListener('resize', this.init.bind(this));
    window.addEventListener('mousemove', this.onMouseMove.bind(this));

    window.requestAnimationFrame(this.animate);
  }

  setColor(hex) {
    this.color = hex;
    this.rgb = this.hexToRgb(hex);
  }

  hexToRgb(hex) {
    hex = hex.replace("#", "");
    if (hex.length === 3) hex = hex.split("").map(c => c + c).join("");
    const hexInt = parseInt(hex, 16);
    return [(hexInt >> 16) & 255, (hexInt >> 8) & 255, hexInt & 255];
  }

  init() {
    this.resizeCanvas();
    this.drawParticles();
  }

  onMouseMove(e) {
    const rect = this.canvas.getBoundingClientRect();
    const { w, h } = this.canvasSize;
    const x = e.clientX - rect.left - w / 2;
    const y = e.clientY - rect.top - h / 2;
    const inside = x < w / 2 && x > -w / 2 && y < h / 2 && y > -h / 2;
    if (inside) {
      this.mouse.x = x;
      this.mouse.y = y;
    }
  }

  resizeCanvas() {
    this.circles.length = 0;
    this.canvasSize.w = window.innerWidth;
    this.canvasSize.h = window.innerHeight;
    this.canvas.width = this.canvasSize.w * this.dpr;
    this.canvas.height = this.canvasSize.h * this.dpr;
    this.canvas.style.width = `${this.canvasSize.w}px`;
    this.canvas.style.height = `${this.canvasSize.h}px`;
    this.context.scale(this.dpr, this.dpr);
  }

  circleParams() {
    const x = Math.floor(Math.random() * this.canvasSize.w);
    const y = Math.floor(Math.random() * this.canvasSize.h);
    const pSize = Math.floor(Math.random() * 2) + this.size;
    const targetAlpha = parseFloat((Math.random() * 0.6 + 0.1).toFixed(1));
    return {
      x, y,
      translateX: 0, translateY: 0,
      size: pSize,
      alpha: 0,
      targetAlpha,
      dx: (Math.random() - 0.5) * 0.1,
      dy: (Math.random() - 0.5) * 0.1,
      magnetism: 0.1 + Math.random() * 4
    };
  }

  drawCircle(circle, update = false) {
    const { x, y, translateX, translateY, size, alpha } = circle;
    this.context.translate(translateX, translateY);
    this.context.beginPath();
    this.context.arc(x, y, size, 0, 2 * Math.PI);
    this.context.fillStyle = `rgba(${this.rgb[0]}, ${this.rgb[1]}, ${this.rgb[2]}, ${alpha})`;
    this.context.fill();
    this.context.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    if (!update) {
      this.circles.push(circle);
    }
  }

  drawParticles() {
    this.context.clearRect(0, 0, this.canvasSize.w, this.canvasSize.h);
    for (let i = 0; i < this.quantity; i++) {
      this.drawCircle(this.circleParams());
    }
  }

  remapValue(value, start1, end1, start2, end2) {
    const remapped = ((value - start1) * (end2 - start2)) / (end1 - start1) + start2;
    return remapped > 0 ? remapped : 0;
  }

  animate() {
    this.context.clearRect(0, 0, this.canvasSize.w, this.canvasSize.h);
    this.circles.forEach((circle, i) => {
      const edge = [
        circle.x + circle.translateX - circle.size,
        this.canvasSize.w - circle.x - circle.translateX - circle.size,
        circle.y + circle.translateY - circle.size,
        this.canvasSize.h - circle.y - circle.translateY - circle.size,
      ];
      const closestEdge = Math.min(...edge);
      const remapClosestEdge = parseFloat(this.remapValue(closestEdge, 0, 20, 0, 1).toFixed(2));
      
      if (remapClosestEdge > 1) {
        circle.alpha += 0.02;
        if (circle.alpha > circle.targetAlpha) circle.alpha = circle.targetAlpha;
      } else {
        circle.alpha = circle.targetAlpha * remapClosestEdge;
      }
      
      circle.x += circle.dx + this.vx;
      circle.y += circle.dy + this.vy;
      circle.translateX += (this.mouse.x / (this.staticity / circle.magnetism) - circle.translateX) / this.ease;
      circle.translateY += (this.mouse.y / (this.staticity / circle.magnetism) - circle.translateY) / this.ease;

      this.drawCircle(circle, true);

      if (
        circle.x < -circle.size ||
        circle.x > this.canvasSize.w + circle.size ||
        circle.y < -circle.size ||
        circle.y > this.canvasSize.h + circle.size
      ) {
        this.circles.splice(i, 1);
        this.drawCircle(this.circleParams());
      }
    });
    window.requestAnimationFrame(this.animate);
  }
}

// Auto-initialize if canvas is found
function particlesThemeColor() {
  return document.documentElement.getAttribute('data-theme') === 'light' ? '#1E293B' : '#ffffff';
}

document.addEventListener('DOMContentLoaded', () => {
  const canvas = document.getElementById('particles-canvas');
  if (canvas) {
    const instance = new ParticlesBackground(canvas, {
      quantity: 150,
      staticity: 60,
      ease: 50,
      color: particlesThemeColor()
    });
    window.addEventListener('themechanged', () => instance.setColor(particlesThemeColor()));
  }
});
