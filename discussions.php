<?php
// Database connection
$host = 'localhost'; // Adjust if necessary
$dbname = 'CCBC';
$username = 'root';
$password = '2WGyoss99*123';

try {
    $pdo = new PDO("mysql:host=$host;dbname=$dbname;charset=utf8", $username, $password);
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
} catch (PDOException $e) {
    die("Database connection failed: " . $e->getMessage());
}

// Handle form submissions
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $course = isset($_POST['course']) ? trim($_POST['course']) : '';
    $topic_number = isset($_POST['topic_number']) && is_numeric($_POST['topic_number']) ? (int)$_POST['topic_number'] : null;
    $topic_name = isset($_POST['topic_name']) ? trim($_POST['topic_name']) : '';
    $topic_description = isset($_POST['topic_description']) ? trim($_POST['topic_description']) : '';
    $topic_id = isset($_POST['topic_id']) && is_numeric($_POST['topic_id']) ? (int)$_POST['topic_id'] : null;

    // Ensure required fields are present
    if (empty($course) || empty($topic_number) || empty($topic_name)) {
      die("Error: Missing required fields.");
    }

    if ($topic_id > 0) {
        // Update existing record
        $stmt = $pdo->prepare("UPDATE discussion_topics SET course = ?, topic_number = ?, topic_name = ?, topic_description = ? WHERE topic_id = ?");

        $stmt->execute([$course, $topic_number, $topic_name, $topic_description, $topic_id]);

        $message = "Topic updated successfully.";
    } else {
        // Insert new record
        $stmt = $pdo->prepare("INSERT INTO discussion_topics (course, topic_number, topic_name, topic_description) VALUES (?, ?, ?, ?)");

        $stmt->execute([$course, $topic_number, $topic_name, $topic_description]);
        $message = "Topic added successfully.";
    }
}

// Fetch all records
$stmt = $pdo->query("SELECT * FROM discussion_topics");
$topics = $stmt->fetchAll(PDO::FETCH_ASSOC);
?>

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Discussion Topics</title>
    <!-- Place the first <script> tag in your HTML's <head> -->
<script src="https://cdn.tiny.cloud/1/w3s1gtjmbvo7mwrwkcj9tbyo0fy32qbpvx5js0xqtr2ft4x3/tinymce/7/tinymce.min.js" referrerpolicy="origin"></script>

<!-- Place the following <script> and <textarea> tags your HTML's <body> -->
<script>
  tinymce.init({
    selector: 'textarea',
    plugins: [
      // Core editing features
      'anchor', 'autolink', 'charmap', 'codesample', 'emoticons', 'image', 'link', 'lists', 'media', 'searchreplace', 'table', 'visualblocks', 'wordcount'
    ],
    toolbar: 'undo redo | blocks fontfamily fontsize | bold italic underline strikethrough | link image media table mergetags | addcomment showcomments | spellcheckdialog a11ycheck typography | align lineheight | checklist numlist bullist indent outdent | emoticons charmap | removeformat',
    tinycomments_mode: 'embedded',
    tinycomments_author: 'Author name',
    mergetags_list: [
      { value: 'First.Name', title: 'First Name' },
      { value: 'Email', title: 'Email' },
    ],
    ai_request: (request, respondWith) => respondWith.string(() => Promise.reject('See docs to implement AI Assistant')),
    exportpdf_converter_options: { 'format': 'Letter', 'margin_top': '1in', 'margin_right': '1in', 'margin_bottom': '1in', 'margin_left': '1in' },
    exportword_converter_options: { 'document': { 'size': 'Letter' } },
    importword_converter_options: { 'formatting': { 'styles': 'inline', 'resets': 'inline',	'defaults': 'inline', } },
  });
</script>

</head>
<body>
    <h1>Manage Discussion Topics</h1>

    <?php if (!empty($message)): ?>
        <p><strong><?= htmlspecialchars($message) ?></strong></p>
    <?php endif; ?>

    <form action="" method="post">
       <input type="hidden" name="topic_id" id="topic_id">
       <div>
           <label for="course">Course:</label>
           <input type="text" name="course" id="course" required value="MNGT140">
       </div>
       <div>
           <label for="topic_number">Topic Number:</label>
           <input type="number" name="topic_number" id="topic_number" min="2" max="8" required>
       </div>
       <div>
           <label for="topic_name">Topic Name:</label>
           <input type="text" name="topic_name" id="topic_name" required>
       </div>
       <div>
           <label for="description">Description:</label>
           <textarea name="topic_description" id="topic_description"></textarea>
       </div>
       <button type="submit">Save</button>
       <button type="reset" onclick="clearForm()">Clear</button>
   </form>

   <h2>Existing Topics</h2>
   <table border="1">
       <thead>
           <tr>
               <th>ID</th>
               <th>Course</th>
               <th>Topic Number</th>
               <th>Topic Name</th>
               <th>Description</th>
               <th>Actions</th>
           </tr>
       </thead>
       <tbody>
           <?php foreach ($topics as $topic): ?>
               <tr>
                   <td><?= htmlspecialchars($topic['topic_id']) ?></td>
                   <td><?= htmlspecialchars($topic['course']) ?></td>
                   <td><?= htmlspecialchars($topic['topic_number']) ?></td>
                   <td><?= htmlspecialchars($topic['topic_name']) ?></td>
                   <td><?= htmlspecialchars($topic['topic_description']) ?></td>
                   <td>
                       <button onclick="editTopic(<?= htmlspecialchars(json_encode($topic)) ?>)">Edit</button>
                   </td>
               </tr>
           <?php endforeach; ?>
       </tbody>
   </table>

   <script>
    function editTopic(topic) {
        document.getElementById('topic_id').value = topic.topic_id;
        document.getElementById('course').value = topic.course;
        document.getElementById('topic_number').value = topic.topic_number;
        document.getElementById('topic_name').value = topic.topic_name;

        // Properly decode HTML entities before loading into TinyMCE
        const parser = new DOMParser();
        const decodedDescription = parser.parseFromString(topic.topic_description, 'text/html').body.textContent;

        tinymce.get('topic_description').setContent(decodedDescription); // Set content into TinyMCE editor
        // Scroll to the top of the page
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    function clearForm() {
        document.getElementById('topic_id').value = '';
        document.getElementById('course').value = 'MNGT140';
        document.getElementById('topic_number').value = '';
        document.getElementById('topic_name').value = '';
        tinymce.get('topic_description').setContent(''); // Clear TinyMCE content
    }
</script>

</body>
</html>
