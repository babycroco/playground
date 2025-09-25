let todos = ["Buy milk", "Learn VS Code", "Push to GitHub"];
todos.push("Celebrate my first GitHub push!");
console.log("My todos:", todos);

// Mark first todo as done
todos[0] = "[x] " + todos[0];

console.log("Updated todos:", todos);