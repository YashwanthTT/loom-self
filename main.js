// Arrow function with template literals
const greetUser = (name) => {
  return `Hello, ${name}! Welcome back.`;
};

console.log(greetUser("Alice"));

// Array manipulation and iteration
const fruits = ["Apple", "Banana"];
fruits.push("Orange"); // Adds to the end

// Loop through array items
fruits.forEach((fruit, index) => {
  console.log(`Fruit ${index + 1}: ${fruit}`);
});
