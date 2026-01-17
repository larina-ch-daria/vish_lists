<script>
  const plants = [
    "/static/images/plant1.png",
    "/static/images/plant2.png",
    "/static/images/plant3.png",
    "/static/images/plant4.png",
    "/static/images/plant5.png",
    "/static/images/plant6.png",
    "/static/images/plant7.png"
  ];

  const chosen = plants[Math.floor(Math.random() * plants.length)];

  const plantDiv = document.getElementById("cornerPlant");
  plantDiv.style.backgroundImage = `url("${chosen}?v=${Date.now()}")`;

</script>
